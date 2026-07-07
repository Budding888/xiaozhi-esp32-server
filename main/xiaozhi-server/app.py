# SSL 兼容性补丁：绕过 Windows 证书存储损坏导致的 SSLError
# Windows 证书存储中的损坏证书会导致 ssl.create_default_context() 失败，
# 从而阻止 aiohttp 等库导入。此补丁在检测到错误时自动切换到 certifi 证书。
import ssl as _ssl
try:
    _ssl.create_default_context()
except _ssl.SSLError:
    import certifi as _certifi
    _original_create_default_context = _ssl.create_default_context
    def _patched_create_default_context(*args, **kwargs):
        try:
            return _original_create_default_context(*args, **kwargs)
        except _ssl.SSLError:
            _ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
            _ctx.load_verify_locations(_certifi.where())
            return _ctx
    _ssl.create_default_context = _patched_create_default_context

import os
import sys
import uuid
import signal
import asyncio
from aioconsole import ainput
from config.settings import load_config
from config.logger import setup_logging
from core.utils.util import get_local_ip, validate_mcp_endpoint
from core.http_server import SimpleHttpServer
from core.websocket_server import WebSocketServer
from core.utils.util import check_ffmpeg_installed
from core.utils.gc_manager import get_gc_manager
from config.config_loader import get_project_dir

# AgentScope 多智能体配置日志
_AGENTSCOPE_LOG_TEMPLATE = """
╔══════════════════════════════════════════════════════════╗
║              AgentScope 多智能体配置                     ║
╠══════════════════════════════════════════════════════════╣
║  模式:       {mode:<20}                        ║
║  启用状态:   {enabled:<21}                       ║
║  启用场景:   {scenes:<21}                       ║
╠──────────────────────────────────────────────────────────╣
║  管道:       {pipeline:<21}                       ║
║  Stages:     {stages:<21}                       ║
║  超时:       {timeout:<21}                       ║
║  降级策略:   {fallback:<21}                       ║
╠──────────────────────────────────────────────────────────╣
║  模型缓存:   {cache:<21}                       ║
║  缓存 TTL:   {cache_ttl:<21}                       ║
╚══════════════════════════════════════════════════════════╝"""


import yaml


def _read_agentscope_config() -> dict:
    """直接从 config.yaml 读取 agentscope 配置段，不依赖 config loader 合并结果"""
    try:
        config_path = os.path.join(get_project_dir(), "config.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return raw.get("agentscope", {})
    except Exception:
        return {}


def _log_agentscope_config(config: dict) -> None:
    """
    打印 AgentScope 多智能体配置信息。

    优先使用 load_config() 合并/API 返回中的 agentscope 段，
    若不存在则回退到直接从 config.yaml 读取（API 远程配置可能不含该段）。
    """
    ascope = config.get("agentscope", {}) or _read_agentscope_config()
    pipelines = ascope.get("pipelines", {})
    model_wrapper = ascope.get("model_wrapper", {})

    # 获取第一个管道的配置信息（如果有）
    pipeline_name = "—"
    pipeline_stages = "—"
    pipeline_timeout = "—"
    pipeline_fallback = "—"
    if pipelines:
        first_name = next(iter(pipelines))
        pipeline_name = first_name
        pipe = pipelines[first_name]
        stages = pipe.get("stages", [])
        pipeline_stages = ", ".join(
            list({next(iter(s.keys())) for s in stages})[:5]
        ) or "—"
        pipeline_timeout = str(pipe.get("timeout", "—"))
        pipeline_fallback = pipe.get("fallback", "—")

    cache_enabled = model_wrapper.get("cache_enabled", False)
    cache_ttl = model_wrapper.get("cache_ttl", "—")

    scenes = ascope.get("enabled_scenes", [])
    scenes_str = ", ".join(scenes) if scenes else "—"

    logger.bind(tag=TAG).info(
        _AGENTSCOPE_LOG_TEMPLATE.format(
            mode=ascope.get("mode", "legacy"),
            enabled=str(ascope.get("enabled", False)),
            scenes=scenes_str,
            pipeline=pipeline_name,
            stages=pipeline_stages[:21],
            timeout=pipeline_timeout,
            fallback=pipeline_fallback,
            cache=str(cache_enabled),
            cache_ttl=str(cache_ttl),
        )
    )

TAG = __name__
logger = setup_logging()


async def wait_for_exit() -> None:
    """
    阻塞直到收到 Ctrl‑C / SIGTERM。
    - Unix: 使用 add_signal_handler
    - Windows: 依赖 KeyboardInterrupt
    """
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    if sys.platform != "win32":  # Unix / macOS
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
        await stop_event.wait()
    else:
        # Windows：await一个永远pending的fut，
        # 让 KeyboardInterrupt 冒泡到 asyncio.run，以此消除遗留普通线程导致进程退出阻塞的问题
        try:
            await asyncio.Future()
        except KeyboardInterrupt:  # Ctrl‑C
            pass


async def monitor_stdin():
    """监控标准输入，消费回车键"""
    while True:
        await ainput()  # 异步等待输入，消费回车


async def main():
    check_ffmpeg_installed()
    config = load_config()

    # 打印 AgentScope 多智能体配置信息
    _log_agentscope_config(config)

    # auth_key优先级：配置文件server.auth_key > manager-api.secret > 自动生成
    # auth_key用于jwt认证，比如视觉分析接口的jwt认证、ota接口的token生成与websocket认证
    # 获取配置文件中的auth_key
    auth_key = config["server"].get("auth_key", "")
    
    # 验证auth_key，无效则尝试使用manager-api.secret
    if not auth_key or len(auth_key) == 0 or "你" in auth_key:
        auth_key = config.get("manager-api", {}).get("secret", "")
        # 验证secret，无效则生成随机密钥
        if not auth_key or len(auth_key) == 0 or "你" in auth_key:
            auth_key = str(uuid.uuid4().hex)
    
    config["server"]["auth_key"] = auth_key

    # 添加 stdin 监控任务
    stdin_task = asyncio.create_task(monitor_stdin())

    # 启动全局GC管理器（5分钟清理一次）
    gc_manager = get_gc_manager(interval_seconds=300)
    await gc_manager.start()

    # 启动 WebSocket 服务器
    ws_server = WebSocketServer(config)
    ws_task = asyncio.create_task(ws_server.start())
    # 启动 Simple http 服务器
    ota_server = SimpleHttpServer(config)
    ota_task = asyncio.create_task(ota_server.start())

    read_config_from_api = config.get("read_config_from_api", False)
    port = int(config["server"].get("http_port", 8003))
    if not read_config_from_api:
        logger.bind(tag=TAG).info(
            "OTA接口是\t\thttp://{}:{}/xiaozhi/ota/",
            get_local_ip(),
            port,
        )
    logger.bind(tag=TAG).info(
        "视觉分析接口是\thttp://{}:{}/mcp/vision/explain",
        get_local_ip(),
        port,
    )
    mcp_endpoint = config.get("mcp_endpoint", None)
    if mcp_endpoint is not None and "你" not in mcp_endpoint:
        # 校验MCP接入点格式
        if validate_mcp_endpoint(mcp_endpoint):
            logger.bind(tag=TAG).info("mcp接入点是\t{}", mcp_endpoint)
            # 将mcp计入点地址转成调用点
            mcp_endpoint = mcp_endpoint.replace("/mcp/", "/call/")
            config["mcp_endpoint"] = mcp_endpoint
        else:
            logger.bind(tag=TAG).error("mcp接入点不符合规范")
            config["mcp_endpoint"] = "你的接入点 websocket地址"

    # 获取WebSocket配置，使用安全的默认值
    websocket_port = 8000
    server_config = config.get("server", {})
    if isinstance(server_config, dict):
        websocket_port = int(server_config.get("port", 8000))

    logger.bind(tag=TAG).info(
        "Websocket地址是\tws://{}:{}/xiaozhi/v1/",
        get_local_ip(),
        websocket_port,
    )

    logger.bind(tag=TAG).info(
        "=======上面的地址是websocket协议地址，请勿用浏览器访问======="
    )
    logger.bind(tag=TAG).info(
        "如想测试websocket请用谷歌浏览器打开test目录下的test_page.html"
    )
    logger.bind(tag=TAG).info(
        "=============================【服务启动完成】================================\n"
    )

    try:
        await wait_for_exit()  # 阻塞直到收到退出信号
    except asyncio.CancelledError:
        print("任务被取消，清理资源中...")
    finally:
        # 停止全局GC管理器
        await gc_manager.stop()

        # 取消所有任务（关键修复点）
        stdin_task.cancel()
        ws_task.cancel()
        if ota_task:
            ota_task.cancel()

        # 等待任务终止（必须加超时）
        await asyncio.wait(
            [stdin_task, ws_task, ota_task] if ota_task else [stdin_task, ws_task],
            timeout=3.0,
            return_when=asyncio.ALL_COMPLETED,
        )
        print("服务器已关闭，程序退出。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("手动中断，程序终止。")

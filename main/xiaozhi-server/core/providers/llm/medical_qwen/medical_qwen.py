"""
医疗Qwen3.5-4B-Medical Provider
对接外部项目通过 AutoTokenizer.from_pretrained 启动的服务
接口格式：OpenAI 兼容 /v1/chat/completions
"""

import time
import json
import urllib.request
import urllib.error
from urllib.parse import urlparse
import threading
from openai import OpenAI
from config.logger import setup_logging
from core.providers.llm.base import LLMProviderBase

TAG = __name__
logger = setup_logging()


class LLMProvider(LLMProviderBase):
    """
    医疗Qwen3.5-4B-Medical Provider

    对接外部医疗Qwen服务（OpenAI兼容接口），仅用于腹透医疗问答。
    不参与function_call工具调度，仅做知识推理。

    ## 健康检查机制
    - health_check() 类方法：GET {base_root}/health 检测服务是否存活
    - 响应格式：{"status": "healthy", "status_code": 200, ...}
    - 5s 超时，30s 缓存避免每次医疗问答都做探针
    """

    _health_cache: dict = {}          # {base_url: (healthy, timestamp)}
    _health_cache_lock = threading.Lock()
    HEALTH_CACHE_TTL = 30             # 缓存有效期（秒）
    HEALTH_TIMEOUT = 5                # 健康检查超时（秒）

    def __init__(self, config):
        self.model_name = config.get("model_name", "Qwen3.5-4B-Medical")
        self.base_url = config.get("base_url", "http://localhost:8104/v1")
        self.api_key = config.get("api_key", "not-needed")
        self.timeout = config.get("timeout", 60)

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
        )
        logger.bind(tag=TAG).info( f"===========MedicalQwen Provider 初始化===========: model={self.model_name}, url={self.base_url}" )


    @classmethod
    def health_check(cls, config: dict) -> bool:
        """
        检测 MedicalQwen 服务是否存活（类方法，可无实例调用）

        向 {base_root}/health 发送 GET 请求，根据返回的 status 字段判断。
        结果缓存 30s 避免重复探针。

        Args:
            config: MedicalQwen 配置字典（需含 health_check_url）

        Returns:
            bool: True=服务正常, False=不可用
        """
        health_check_url = config.get("health_check_url", "")
        now = time.time()

        # 读缓存（以 health_check_url 为 key，因为同一服务共享缓存）
        with cls._health_cache_lock:
            if health_check_url in cls._health_cache:
                healthy, ts = cls._health_cache[health_check_url]
                if now - ts < cls.HEALTH_CACHE_TTL:
                    return healthy

        # 执行健康检查：GET {health_check_url}
        # 打印health_check_url
        logger.bind(tag=TAG).info(f"=============MedicalQwen 健康检查health_check_url: {health_check_url}")
        healthy = False
        try:
            req = urllib.request.Request(health_check_url, method="GET")
            # 设置超时
            with urllib.request.urlopen(req, timeout=cls.HEALTH_TIMEOUT) as resp:
                if resp.status == 200:
                    body = resp.read().decode("utf-8")
                    data = json.loads(body)
                    logger.bind(tag=TAG).info(f"=============MedicalQwen 健康检查data: {data}")
                    if data.get("status_code") == 200:
                        healthy = True
                        logger.bind(tag=TAG).info(
                            f"=============MedicalQwen 健康检查通过: {health_check_url}, "
                            f"model={data.get('model')}, slots={data.get('parallel_slots')}"
                        )
                    else:
                        logger.bind(tag=TAG).warning(
                            f"=============MedicalQwen 健康检查返回非 healthy 状态: {data.get('status')}"
                        )
                else:
                    logger.bind(tag=TAG).warning(
                        f"=============MedicalQwen 健康检查 HTTP {resp.status}: {health_check_url}"
                    )
        except urllib.error.URLError as e:
            logger.bind(tag=TAG).warning(f"=============MedicalQwen 健康检查连接失败: {e.reason}")
        except json.JSONDecodeError as e:
            logger.bind(tag=TAG).warning(f"=============MedicalQwen 健康检查响应解析失败: {e}")
        except Exception as e:
            logger.bind(tag=TAG).warning(f"=============MedicalQwen 健康检查异常: {e}")

        # 写缓存
        with cls._health_cache_lock:
            cls._health_cache[health_check_url] = (healthy, now)

        return healthy

    def response(self, session_id, dialogue, **kwargs):
        """流式响应"""
        try:
            # 模型参数使用医疗大模型的参数，调用者不指定
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=dialogue,
                # temperature=kwargs.get("temperature", 0.45),
                # max_tokens=kwargs.get("max_tokens", 1024),
                # top_p=kwargs.get("top_p", 0.85),
                stream=True,
            )
            for chunk in stream:
                if getattr(chunk, "choices", None):
                    delta = chunk.choices[0].delta
                    content = getattr(delta, "content", "") or ""
                    yield content

        except Exception as e:
            logger.bind(tag=TAG).error(f"MedicalQwen 流式响应失败: {e}")
            yield ""

    def response_no_stream(self, system_prompt, user_prompt, **kwargs):
        """非流式响应（供 medical_qa 插件调用）"""
        dialogue = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=dialogue,
                temperature=kwargs.get("temperature", 0.45),
                max_tokens=kwargs.get("max_tokens", 1024),
                top_p=kwargs.get("top_p", 0.9),
                stream=False,
            )
            return resp.choices[0].message.content

        except Exception as e:
            logger.bind(tag=TAG).error(f"MedicalQwen 非流式响应失败: {e}")
            return ""

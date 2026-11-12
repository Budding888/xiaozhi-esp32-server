import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler
TAG = __name__


async def handleAbortMessage(
    conn: "ConnectionHandler", save_interrupted_query: bool = True
):
    """硬中断本轮播报（abort != goodbye）。

    作用：立即终止 LLM 流式推理、停止 TTS 播放并丢弃本地音频队列，
    但保持 WebSocket 连接与对话历史不变，会话可继续使用。

    Args:
        conn: 连接处理器
        save_interrupted_query: 是否把被中断的问题放入「中断恢复询问」队列。
            用户主动说出/输入 abort_commands 指令时应传 False，
            避免用户明确要求停止后又被追问「是否继续解答」。
    """
    if conn.close_after_chat or conn.is_exiting:
        conn.logger.bind(tag=TAG).info("退出流程中被打断，直接关闭连接")
        return

    conn.logger.bind(tag=TAG).info("Abort message received")

    # 记录中断代次：用于识别「LLM 请求尚未返回时用户已要求停止」的竞态，
    # 避免 chat() 新一轮开始时把中断标记清掉后继续播报
    conn.abort_generation = getattr(conn, "abort_generation", 0) + 1

    # 保存被中断的问题到队列，供 chat() 完成后询问用户是否恢复
    # 由 config.yaml 的 enable_resume_inquiry 开关控制：关闭时不做「中断恢复询问」
    enable_resume_inquiry = (
        conn.config.get("enable_resume_inquiry", True) and save_interrupted_query
    )
    if conn.current_query:
        if enable_resume_inquiry:
            conn.interrupted_queries.append(conn.current_query)
            conn.logger.bind(tag=TAG).info(
                f"保存被中断的问题到恢复队列: {conn.current_query}, "
                f"当前队列长度: {len(conn.interrupted_queries)}"
            )
        else:
            conn.logger.bind(tag=TAG).debug(
                f"中断恢复询问已关闭(enable_resume_inquiry=False)或本次为显式停止命令，"
                f"不保存被中断的问题: {conn.current_query}"
            )
    else:
        conn.logger.bind(tag=TAG).debug(
            "current_query 为空，跳过保存被中断的问题"
        )

    # 设置成打断状态，会自动打断llm、tts任务
    conn.client_abort = True
    conn.clear_queues()
    # 打断客户端说话状态
    await conn.websocket.send(
        json.dumps({"type": "tts", "state": "stop", "session_id": conn.session_id})
    )
    conn.clearSpeakStatus()
    conn.logger.bind(tag=TAG).info("Abort message received-end")

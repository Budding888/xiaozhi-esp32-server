import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler
TAG = __name__


async def handleAbortMessage(conn: "ConnectionHandler"):
    if conn.close_after_chat or conn.is_exiting:
        conn.logger.bind(tag=TAG).info("退出流程中被打断，直接关闭连接")
        return
        
    conn.logger.bind(tag=TAG).info("Abort message received")

    # 保存被中断的问题到队列，供 chat() 完成后询问用户是否恢复
    # 由 config.yaml 的 enable_resume_inquiry 开关控制：关闭时不做「中断恢复询问」
    enable_resume_inquiry = conn.config.get("enable_resume_inquiry", True)
    if conn.current_query:
        if enable_resume_inquiry:
            conn.interrupted_queries.append(conn.current_query)
            conn.logger.bind(tag=TAG).info(
                f"保存被中断的问题到恢复队列: {conn.current_query}, "
                f"当前队列长度: {len(conn.interrupted_queries)}"
            )
        else:
            conn.logger.bind(tag=TAG).debug(
                f"中断恢复询问已关闭(enable_resume_inquiry=False)，不保存被中断的问题: "
                f"{conn.current_query}"
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

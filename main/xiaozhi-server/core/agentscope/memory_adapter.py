"""
xiaozhi Dialogue → AgentScope 状态适配器 (2.0.2)

将 xiaozhi 现有 Dialogue 对话管理器包装为 AgentScope AgentState，
使 Agent 可以访问现有对话历史。

使用方式:
    memory = XiaozhiMemoryAdapter(conn.dialogue)
"""

from agentscope.message import Msg
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class XiaozhiMemoryAdapter:
    """
    xiaozhi Dialogue → AgentScope 状态适配器。

    将现有 xiaozhi Dialogue 对话管理器包装为 AgentScope 兼容的
    内存接口，使 AgentScope Agent 可以访问现有对话历史。

    注意: 这是一个轻量适配器，不复制数据，而是直接引用现有 Dialogue。
    AgentScope 2.0.2 使用 AgentState 管理推理上下文，此适配器
    主要用于初始对话历史导入和同步。

    属性:
        dialogue: xiaozhi 现有 Dialogue 实例
        _memory: 内部消息列表（Msg 对象）
    """

    def __init__(self, dialogue):
        """
        初始化适配器。

        Args:
            dialogue: xiaozhi Dialogue 实例（core/utils/dialogue.py）
        """
        self.dialogue = dialogue
        self._memory: list[Msg] = []

        # 将现有对话历史导入
        self._import_history()

    def _import_history(self):
        """
        将 xiaozhi Dialogue 中的历史消息导入内部列表。

        只导入最近 10 轮（20条消息）。
        """
        try:
            history = getattr(self.dialogue, "dialogue", [])
            if not history:
                return

            recent = history[-20:] if len(history) > 20 else history

            for msg in recent:
                role_mapping = {
                    "user": "user",
                    "assistant": "assistant",
                    "system": "system",
                    "tool": "assistant",
                }
                role = role_mapping.get(
                    getattr(msg, "role", "user"), "user"
                )
                content = getattr(msg, "content", "") or ""

                if content:
                    from agentscope.message import TextBlock
                    self._memory.append(
                        Msg(
                            name=role,
                            content=[TextBlock(text=content)],
                            role=role,
                        )
                    )
        except Exception as e:
            logger.bind(tag=TAG).debug(f"导入对话历史失败（非关键错误）: {e}")

    def add_message(self, msg: Msg):
        """添加消息到内存"""
        # 确保 content 是列表格式（2.0.2 要求）
        if not isinstance(msg.content, list):
            from agentscope.message import TextBlock
            msg.content = [TextBlock(text=str(msg.content))]
        self._memory.append(msg)

    def get_memory(self, recent_n: int = 10) -> list:
        """获取最近的对话历史"""
        if len(self._memory) > recent_n:
            return self._memory[-recent_n:]
        return self._memory

    def clear(self):
        """清空内存"""
        self._memory.clear()

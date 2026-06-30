"""
AgentScope Agent 工厂 (2.0.2)

创建和配置基于 AgentScope 2.0.2 的智能体实例，
与现有 xiaozhi 系统的 Provider 和插件系统集成。

使用方式:
    factory = AgentScopeFactory(conn)
    agent = factory.create_general_agent()
    result = agent(inputs=[Msg("user", question, "user")])
"""

from agentscope.agent import Agent, ReActConfig, ContextConfig, ModelConfig
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class AgentScopeFactory:
    """
    AgentScope 2.0.2 智能体工厂。

    创建和配置基于 AgentScope 的智能体实例。
    使用 Agent + ReActConfig 替代 1.x 的 ReActAgent。

    属性:
        conn: ConnectionHandler 实例
        model_wrapper: XiaozhiLLMWrapper 实例
        toolkit: XiaozhiToolkitWrapper 实例
    """

    def __init__(self, conn):
        """
        初始化工厂。

        Args:
            conn: ConnectionHandler 实例
        """
        self.conn = conn
        self.model_wrapper = None
        self.toolkit = None

        self._init_components()

    def _init_components(self):
        """初始化 AgentScope 组件"""
        try:
            from core.agentscope.model_wrapper import (
                XiaozhiLLMWrapper,
                XiaozhiCredential,
            )
            from core.agentscope.toolkit_wrapper import XiaozhiToolkitWrapper

            llm = getattr(self.conn, "llm", None)
            if llm:
                credential = XiaozhiCredential(llm)
                self.model_wrapper = XiaozhiLLMWrapper(
                    credential=credential,
                    model=getattr(llm, "model_name", "xiaozhi-llm"),
                    session_id=getattr(self.conn, "device_id", ""),
                )

            if hasattr(self.conn, "func_handler") and self.conn.func_handler:
                self.toolkit = XiaozhiToolkitWrapper(self.conn)

            logger.bind(tag=TAG).info(
                f"============AgentScope 组件初始化完成: "
                f"model={'✅' if self.model_wrapper else '❌'}, "
                f"toolkit={'✅' if self.toolkit else '❌'}============"
            )
        except Exception as e:
            logger.bind(tag=TAG).error(f"AgentScope 组件初始化失败: {e}")

    def create_medical_reasoner(self, sys_prompt: str = None) -> Agent:
        """
        创建医疗推理 Agent。

        Args:
            sys_prompt: 系统提示词

        Returns:
            Agent: 配置好的医疗推理 Agent
        """
        if not self.model_wrapper:
            logger.bind(tag=TAG).error("ModelWrapper 未初始化")
            return None

        prompt = sys_prompt or (
            "你是腹透健康知识问答助手，基于知识库回答患者问题。\n"
            "【核心原则】\n"
            "1. 逐条覆盖知识库中的每一个要点，不得遗漏任何一条；\n"
            "2. 知识库信息不足时，用你的医学知识补充完善；\n"
            "3. 用通俗易懂的口语表达，控制600字以内。"
        )

        agent = Agent(
            name="medical_reasoner",
            system_prompt=prompt,
            model=self.model_wrapper,
            toolkit=self.toolkit,
            react_config=ReActConfig(max_iters=2),
        )
        return agent

    def create_general_agent(
        self, name: str = "assistant", sys_prompt: str = None
    ) -> Agent:
        """
        创建通用对话 Agent。

        Args:
            name: Agent 名称
            sys_prompt: 系统提示词

        Returns:
            Agent: 配置好的通用 Agent
        """
        if not self.model_wrapper:
            return None

        agent = Agent(
            name=name,
            system_prompt=sys_prompt or "你是一名智能语音助手，请用简洁的中文回答问题。",
            model=self.model_wrapper,
            toolkit=self.toolkit,
            react_config=ReActConfig(max_iters=2),
        )
        return agent

    def create_info_aggregator(self) -> Agent:
        """
        创建信息聚合 Agent。

        Returns:
            Agent: 配置好的信息聚合 Agent
        """
        if not self.model_wrapper:
            return None

        agent = Agent(
            name="info_aggregator",
            system_prompt="请收集相关信息后回答用户问题。",
            model=self.model_wrapper,
            toolkit=self.toolkit,
            react_config=ReActConfig(max_iters=3),
        )
        return agent


def create_agentscope_pipeline(conn) -> object:
    """
    便捷函数：从 ConnectionHandler 创建 AgentScope 管道对象。

    Args:
        conn: ConnectionHandler 实例

    Returns:
        AgentScopeFactory: 工厂实例
    """
    return AgentScopeFactory(conn)

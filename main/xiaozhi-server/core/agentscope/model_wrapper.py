"""
xiaozhi LLM Provider → AgentScope ChatModelBase 适配器 (2.0.2)

将现有 xiaozhi LLM Provider 包装为 AgentScope 2.0.2 ChatModelBase 接口，
供 Agent 使用。

使用方式:
    wrapper = XiaozhiLLMWrapper(
        credential=XiaozhiCredential(llm_provider),
        model=getattr(llm_provider, "model_name", "xiaozhi-llm"),
        parameters=XiaozhiLLMWrapper.Parameters(),
        session_id="...",
    )
    response = await wrapper(messages=[Msg("user", "你好", "user")])
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Optional, Sequence
from dataclasses import dataclass

from pydantic import BaseModel
from agentscope.model import ChatModelBase, ChatResponse
from agentscope.message import Msg, TextBlock
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class XiaozhiCredential:
    """
    将 xiaozhi LLM Provider 包装为 AgentScope 凭据对象。

    实现 CredentialBase 的接口（但不继承，避免 Pydantic 字段验证），
    使 XiaozhiLLMWrapper 可以通过 credential.api_key 等属性访问现有 Provider 的信息。
    """

    def __init__(self, llm_provider) -> None:
        self._llm = llm_provider
        self.api_key: str = getattr(llm_provider, "api_key", "") or ""
        self.base_url: str = getattr(llm_provider, "base_url", "") or ""


class XiaozhiLLMWrapper(ChatModelBase):
    """
    适配现有 xiaozhi LLM Provider 到 AgentScope 2.0.2 ChatModelBase 接口。

    AgentScope Agent 通过此包装器调用现有的 LLM Provider，
    无需修改现有 Provider 实现。
    """

    class Parameters(BaseModel):
        """适配器参数（无额外参数，由底层 Provider 自行管理）"""
        temperature: float = 0.7
        max_tokens: int = 2048
        top_p: float = 0.9

    def __init__(
        self,
        credential: XiaozhiCredential,
        model: str,
        parameters: BaseModel | None = None,
        stream: bool = True,
        session_id: str = "",
        **kwargs,
    ) -> None:
        """
        初始化包装器。

        Args:
            credential: XiaozhiCredential 实例（包装现有 LLM Provider）
            model: 模型名称
            parameters: 模型参数（可选，使用默认值）
            stream: 是否流式输出
            session_id: 会话 ID
        """
        super().__init__(
            credential=credential,
            model=model,
            parameters=parameters or self.Parameters(),
            stream=stream,
            max_retries=kwargs.get("max_retries", 0),
            retry_delay=kwargs.get("retry_delay", 1.0),
            context_size=kwargs.get("context_size", 32768),
        )
        self._llm = credential._llm
        self._session_id = session_id

        logger.bind(tag=TAG).info(
            "XiaozhiLLMWrapper initialized | model={}",
            model,
        )

    async def __call__(
        self,
        messages: list[Msg],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        """
        调用底层 LLM Provider。

        Args:
            messages: AgentScope Msg 列表
            tools: 工具定义（暂不支持，透传 None）
            tool_choice: 工具选择策略（暂不支持）

        Returns:
            ChatResponse: AgentScope 标准聊天响应
        """
        dialogue = self._convert_messages(messages)
        if not dialogue:
            return self._build_chat_response("")

        stream = kwargs.get("stream", self.stream)

        if stream:
            return self._stream_response(dialogue)

        return await self._sync_response(dialogue)

    def _convert_messages(self, msgs: list) -> list[dict]:
        """将 AgentScope Msg 列表转换为 xiaozhi dialogue 格式"""
        dialogue = []
        for msg in msgs:
            if isinstance(msg, Msg):
                role = msg.role if msg.role in ("user", "assistant", "system") else "user"
                # Msg.content 在 2.0.2 中是 list[Block]，需提取文本
                content = self._extract_msg_content(msg)
                dialogue.append({"role": role, "content": content})
            elif isinstance(msg, dict):
                role = msg.get("role", "user")
                content = str(msg.get("content", ""))
                dialogue.append({"role": role, "content": content})
        return dialogue

    def _extract_msg_content(self, msg: Msg) -> str:
        """从 Msg 对象中提取文本内容"""
        if isinstance(msg.content, list):
            texts = []
            for block in msg.content:
                if hasattr(block, "text"):
                    texts.append(str(block.text))
                elif isinstance(block, dict):
                    texts.append(str(block.get("text", "")))
            return "".join(texts)
        return str(msg.content) if msg.content else ""

    async def _sync_response(self, dialogue: list[dict]) -> ChatResponse:
        """非流式调用，聚合所有块后返回"""
        full_text = ""
        for chunk in self._llm.response(
            session_id=self._session_id,
            dialogue=dialogue,
        ):
            full_text += chunk

        return self._build_chat_response(full_text)

    def _stream_response(self, dialogue: list[dict]) -> AsyncGenerator[ChatResponse, None]:
        """流式调用"""
        async def _generate():
            for chunk in self._llm.response(
                session_id=self._session_id,
                dialogue=dialogue,
            ):
                yield self._build_chat_response(chunk)

        return _generate()

    def _build_chat_response(self, text: str) -> ChatResponse:
        """构造 AgentScope 2.0.2 ChatResponse（Pydantic BaseModel）"""
        block = TextBlock(text=text)
        response_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()

        return ChatResponse(
            content=[block],
            id=response_id,
            created_at=now,
            type="chat",
            is_last=True,
        )

    def get_llm_provider(self):
        """获取底层 LLM Provider 实例"""
        return self._llm

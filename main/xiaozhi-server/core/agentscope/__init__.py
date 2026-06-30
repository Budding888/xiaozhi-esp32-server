"""
xiaozhi-esp32-server AgentScope Adapter Layer

将 AgentScope 2.0.2 多智能体框架以 Adapter/Wrapper 模式整合进现有系统。
通过 AgentMode=legacy/agentscope 切换，legacy 模式为永久兜底。

核心组件：
- model_wrapper.py:     XiaozhiLLMWrapper — 现有 LLM Provider → AgentScope ChatModelBase
- toolkit_wrapper.py:   XiaozhiToolkitWrapper — 现有插件系统 → AgentScope Toolkit
- memory_adapter.py:    XiaozhiMemoryAdapter — 现有 Dialogue → AgentScope 状态适配
- agent_factory.py:     AgentScopeFactory — 智能体工厂，创建和配置各种智能体
"""

from core.agentscope.model_wrapper import XiaozhiLLMWrapper, XiaozhiCredential
from core.agentscope.toolkit_wrapper import XiaozhiToolkitWrapper
from core.agentscope.memory_adapter import XiaozhiMemoryAdapter
from core.agentscope.agent_factory import AgentScopeFactory

__all__ = [
    "XiaozhiLLMWrapper",
    "XiaozhiCredential",
    "XiaozhiToolkitWrapper",
    "XiaozhiMemoryAdapter",
    "AgentScopeFactory",
]

__version__ = "2.0.0"

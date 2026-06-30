"""
基于 AgentScope 的智能体定义

包含基于 AgentScope 框架封装的智能体，
用于医疗问答、意图路由、内容校验等场景。

使用方式:
    from core.agents.medical_pipeline import agentscope_medical_flow
    result = await agentscope_medical_flow(conn, question)
"""

from .medical_pipeline import agentscope_medical_flow

__all__ = ["agentscope_medical_flow"]

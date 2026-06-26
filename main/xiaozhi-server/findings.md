# 研究发现：MedicalQwen 服务不可用时的降级流程优化

## 背景

当用户询问腹透医疗问题时，系统通过 `search_medical_question` 插件进入医疗问答流水线：
Query改写（MedicalQwen）→ RAGFlow检索 → 知识压缩（通用LLM）→ MedicalQwen推理 → 安全校验

整个流水线耗时 **30~60 秒**。

## 当前问题

### 问题 1：无服务健康检查
`search_medical_question` 启动时没有任何前置健康检查。如果 MedicalQwen（8106端口）已停止，系统仍在流水线第一步（Query改写）就尝试调用 MedicalQwen，白白等待 60s 超时后才降级。

### 问题 2：乐观进度播报误导用户
代码在 `_call_medical_qwen()` 之前就发送了 TTS 进度：
```python
_send_progress_tts(conn, "抱歉，让您久等了。本次查询到的结果汇总如下。")
medical_answer = _call_medical_qwen(conn, question, knowledge_context)
```
如果 MedicalQwen 已挂，用户听完"本次查询到的结果汇总如下"后，紧接着听到"医疗系统繁忙，请稍后再试"，体验极差。

### 问题 3：长超时等待
MedicalQwen Provider 的 `timeout=60`。当服务挂掉时，OpenAI 客户端需要等满 60s（或 TCP 超时）才报错。用户等待 1 分钟只听到一个错误。

### 问题 4：免责声明附加到错误消息
`_direct_medical_and_speak()` 在 `receiveAudioHandle.py` 中 **始终** 附加免责声明：
```python
conn.tts.tts_one_sentence(conn, ContentType.TEXT,
    content_detail="温馨提示：以上内容仅供参考..."
)
```
即使回答是"医疗系统繁忙，请稍后再试"，免责声明也会追加，使错误听起来像医疗回答。

### 问题 5：没有智能降级
当 MedicalQwen 不可用时，直接返回"医疗系统繁忙，请稍后再试"。但如果 RAGFlow 有结果，这些结果被完全丢弃了。可以考虑降级为：
- 直接用 RAGFlow 结果回答（跳过 MedicalQwen 推理）
- 或用通用 LLM 基于 RAGFlow 结果做简要回答

## 相关文件

| 文件 | 作用 | 改动 |
|------|------|------|
| `plugins_func/functions/search_medical_question.py` | 医疗问答编排引擎（核心修改点） | ✅ 重构为多级降级架构 |
| `core/providers/llm/medical_qwen/medical_qwen.py` | MedicalQwen Provider（超时配置） | ✅ 新增 health_check() |
| `core/handle/receiveAudioHandle.py` | `_direct_medical_and_speak()` 入口 | ✅ 移除重复免责声明 |
| `core/connection.py` | `_direct_medical_chat()` 入口 | ✅ 移除重复 TTS 播报 |

## 代码审查发现

| 级别 | 问题 | 修复方式 |
|------|------|---------|
| HIGH | 双重免责声明 | 移除 `_direct_medical_and_speak` 中的声明，由 `_medical_verify` 统一处理 |
| HIGH | 双重 TTS 播报 | 移除 `_direct_medical_chat` REQLLM 分支的 `tts.tts_one_sentence` |
| MEDIUM | log 级别误用 | `warning` → `info` |
| MEDIUM | 注释不准确 | 修正描述 |

---



# 调研发现 — 智能体框架对比

## 适用于本项目的 Python 智能体框架全景

### 候选框架清单

| # | 框架 | 开发者 | 定位 | 嵌入性 | 管道编排 | 社区规模 |
|---|------|--------|------|--------|---------|---------|
| 1 | **AgentScope 2.0** | 阿里通义 | 多Agent开发框架 | ✅ 库模式 | ✅ pipeline | ~5K stars |
| 2 | **smolagents** | HuggingFace | 代码即行动的轻量Agent | ✅ 极轻(~1K行) | ❌ 无(需自行) | ~27K stars |
| 3 | **pydantic-ai v2** | Pydantic团队 | 类型安全的Agent框架 | ✅ 轻量 | ⚠️ pydantic-graph | ~15K stars |
| 4 | **OpenAI Agents SDK** | OpenAI | 轻量多Agent工作流 | ✅ 轻量(~800行core) | ✅ handoff机制 | ~22K stars |
| 5 | **LangGraph** | LangChain | 生产级状态机Agent | ⚠️ 重量级 | ✅ 有向图 | ~10K stars |
| 6 | **CrewAI** | CrewAI | 角色协作多Agent | ⚠️ 中等 | ✅ 顺序/层级 | ~25K stars |
| 7 | **Hermes Agent** | Nous Research | 自我进化个人助手 | ❌ 独立运行时 | ❌ 无 | ~66K stars |

### 关键筛选维度

```
本项目核心约束:
  🔴 必须可嵌入现有Python项目 (非独立运行时)
  🔴 必须兼容现有asyncio事件循环
  🔴 必须能与现有@register_function插件系统集成
  🟡 必须有管道编排能力 (医疗RAG→LLM→校验流程)
  🟡 必须轻量 (纯CPU边缘部署, 内存敏感)

因此直接排除:
  ❌ Hermes Agent — 独立运行时, 事件循环冲突, 太重
  ❌ LangGraph — 重量级(LangChain全栈), 不适合边缘部署
  ❌ CrewAI — 角色扮演开销, 非必需抽象

需进一步评估:
  ✅ smolagents — 极轻量, 但无管道编排
  ✅ pydantic-ai v2 — 轻量类型安全, 但多Agent能力有限
  ✅ OpenAI Agents SDK — 轻量handoff, 但深度绑定OpenAI
  ✅ AgentScope 2.0 — 轻量, 管道编排, asyncio兼容
```

### 四框架详细对比

| 维度 | AgentScope 2.0 | smolagents | pydantic-ai v2 | OpenAI Agents SDK |
|------|---------------|-----------|---------------|-------------------|
| 核心代码量 | ~5000行 | ~1000行 | ~3000行 | ~800行 |
| pip安装 | agentscope | smolagents | pydantic-ai | openai-agents |
| 内存占用 | ~50MB | ~20MB | ~30MB | ~30MB |
| 异步支持 | ✅ 原生asyncio | ✅ asyncio | ✅ asyncio | ✅ asyncio |
| 管道编排 | ✅ sequential/fanout/MsgHub | ❌ 无 | ⚠️ pydantic-graph(可选) | ✅ handoff机制 |
| 工具调用 | Toolkit + FunctionTool | @tool装饰器 + MCP | @agent.tool + MCP | @function_tool + MCP |
| 与@register_function兼容 | ✅ ToolkitWrapper | ❌ 需重写 | ❌ 需重写 | ❌ 需重写 |
| 结构化输出 | ✅ Pydantic model | ❌ 无 | ✅ Pydantic (天生) | ❌ 依赖模型 |
| 多Agent协作 | ✅ MsgHub/pipeline | ⚠️ ManagedAgent | ❌ 单Agent为主 | ✅ handoff |
| 记忆管理 | InMemoryMemory | ❌ 无 | ❌ 无 | ✅ SQLiteSession |
| 模型兼容 | OpenAI/DashScope等 | 100+ (LiteLLM) | 多provider | 强OpenAI绑定 |
| 社区规模 | ~5K stars | ~27K stars | ~15K stars | ~22K stars |
| 中文生态 | ✅ 阿里云原生完善 | ❌ 英文为主 | ❌ 英文为主 | ❌ 英文为主 |
| API稳定性 | ✅ 相对稳定 | ⚠️ v0.x快速迭代 | ✅ v2.0稳定 | ✅ 稳定 |
| 边缘部署 | ✅ 纯CPU轻量 | ✅ 极轻 | ✅ Monty Rust沙箱 | ✅ 轻量 |

### 适配性综合评分

| 框架 | 嵌入性 | 管道编排 | 插件兼容 | asyncio兼容 | 轻量 | 总分 |
|------|--------|---------|---------|------------|------|------|
| **AgentScope 2.0** | 9/10 | 9/10 | 9/10 | 9/10 | 8/10 | **44/50** |
| smolagents | 9/10 | 2/10 | 4/10 | 8/10 | 10/10 | 33/50 |
| pydantic-ai v2 | 8/10 | 5/10 | 4/10 | 8/10 | 9/10 | 34/50 |
| OpenAI Agents SDK | 8/10 | 7/10 | 4/10 | 8/10 | 9/10 | 36/50 |
| LangGraph | 5/10 | 9/10 | 5/10 | 6/10 | 3/10 | 28/50 |
| CrewAI | 6/10 | 7/10 | 4/10 | 6/10 | 5/10 | 28/50 |
| Hermes Agent | 3/10 | 2/10 | 3/10 | 3/10 | 3/10 | 14/50 |

### 各框架集成调整需求

| 框架 | 集成方式 | 适配器需要 | 现有代码改动 | 预期周期 |
|------|---------|-----------|------------|---------|
| **AgentScope 2.0** | 库模式import | ModelWrapper + ToolkitWrapper | 最小(~3文件) | 3-4天 |
| smolagents | 库模式import | 重写工具为@tool + 自行实现管道 | 中等(~5文件) | 5-7天 |
| pydantic-ai v2 | 库模式import | 重写工具为@agent.tool + 自行实现管道 | 中等(~5文件) | 5-7天 |
| OpenAI Agents SDK | 库模式import | 重写工具为@function_tool + 自行适配provider | 中等(~5文件) | 5-7天 |
| LangGraph | 库模式import | 大量改造(图定义+节点+边) | 大(~10文件) | 7-10天 |
| CrewAI | 库模式import | 角色定义 + 工具重写 | 大(~8文件) | 7-10天 |
| Hermes Agent | 独立进程API | HTTP桥接客户端 | 最小(~2文件) | 2-3天 |

### 最终排序

```
1st 🥇 AgentScope 2.0     — 总分44/50, 最全面适合本项目
2nd 🥈 OpenAI Agents SDK  — 总分36/50, 但强OpenAI绑定导致灵活性不足
3rd 🥉 pydantic-ai v2     — 总分34/50, 类型安全但缺管道编排和多Agent
4th    smolagents          — 总分33/50, 极轻但功能不够
```

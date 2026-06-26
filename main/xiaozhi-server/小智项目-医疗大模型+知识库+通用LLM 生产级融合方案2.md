# 小智项目 - AgentScope 2.0 多智能体框架整合可行性方案

> **版本**: v2.1  
> **基于**: AgentScope 2.0 Python 版 + xiaozhi-esp32-server 现有架构  
> **适用场景**: 医疗大模型 + 知识库(RAG) + 通用LLM 生产级融合  
> **硬件约束**: 纯CPU边缘部署，适配音箱硬件  
> **最后更新**: 2026-06-26

---

## 目录

1. [现状全面分析](#一现状全面分析)
2. [AgentScope 2.0 Python 能力评估](#二agentscope-20-python-能力评估)
3. [可行性分析](#三可行性分析)
4. [核心数据流设计](#四核心数据流设计)
5. [集成方案设计](#五集成方案设计)
6. [智能体层适配设计](#六智能体层适配设计)
7. [配置系统设计](#七配置系统设计)
8. [迁移路线图](#八迁移路线图)
9. [验证方案](#九验证方案)
10. [生产保障](#十生产保障)
11. [风险评估](#十一风险评估)
12. [决策建议](#十二决策建议)

---

## 一、现状全面分析

### 1.1 当前项目架构（六层模型）

xiaozhi-esp32-server 当前采用 **Provider 模式 + 事件驱动管道** 架构，已实现完整的语音交互链路：

```
WebSocket Client → ConnectionHandler → VAD → ASR → Intent → LLM → TTS → WebSocket Client
```

#### 六层架构总览

| 层 | 核心组件 | 职责 |
|----|---------|------|
| **Layer 1: 网络传输层** | WebSocket Server (:8000) + HTTP Server (:8003) | 设备连接、OTA下载、Vision API |
| **Layer 2: 连接管理层** | ConnectionHandler (~1700行) | 全生命周期管理、状态维护、超时控制 |
| **Layer 3: 消息处理层** | textHandler/注册表 + flat handlers | JSON消息解析、按类型分发 |
| **Layer 4: 提供者层** | core/providers/{ASR,TTS,LLM,...} | AI能力抽象基类 + 多实现 |
| **Layer 5: 工具/插件层** | UnifiedToolHandler + plugins_func | 函数注册、路由、执行 |
| **Layer 6: 配置系统** | config.yaml + .config.yaml + config_from_api | 多级配置合并、热加载 |

### 1.2 医疗模块现状（三级入口架构）

当前 `search_medical_question` 插件（1120行）已实现三级的医疗检测和 V2 并行融合流程：

```
Level 1: ASR文本后预过滤 (receiveAudioHandle.py:startToChat)
  → _is_medical_query() 关键词匹配 (~40个)
  → _direct_medical_and_speak() 直接进入医疗管道

Level 2: chat() 中二次过滤 (connection.py:chat)
  → 同上关键词匹配，作为兜底
  
Level 3: LLM function_call 调用
  → search_medical_question 作为普通插件，依赖LLM判断
```

**V2 并行流核心流程**：

```
search_medical_question(question)
  │
  ├─ Health Check → MedicalQwen 健康? 
  │    ├─ ✅ 健康 → V2并行流
  │    │    ├─ Thread A: RAGFlow检索 (top_k=12, score≥0.6)
  │    │    └─ Thread B: MedicalQwen推理 (temp=0.35)
  │    │    └─ 通用LLM融合 (merge + verify)
  │    │
  │    └─ ❌ 不健康 → 降级流
  │         └─ RAGFlow检索 → 通用LLM回答
  │         └─ 或者纯通用LLM回答
```

### 1.3 ✅ 已实现的功能

| 功能 | 状态 | 位置 |
|------|------|------|
| MedicalQwen Provider (OpenAI兼容) | ✅ | `core/providers/llm/medical_qwen/` |
| 医疗关键词检测 (~40个) | ✅ | `core/connection.py:_is_medical_query()` |
| RAGFlow知识库检索 (v2 API) | ✅ | `plugins_func/functions/search_from_ragflow.py` |
| V2并行融合 (ThreadPoolExecutor) | ✅ | `search_medical_question.py:_medical_search_flow_v2()` |
| 内容校验 (禁忌词+免责声名) | ✅ | `search_medical_question.py:_medical_verify()` |
| 健康检查+30s缓存 | ✅ | `search_medical_question.py:LLMProvider.health_check()` |
| 三级降级机制 | ✅ | 健康→并行流 / 不健康→降级流 / 无结果→通用LLM |
| 查询优化 (口语→关键词) | ✅ | `_optimize_rag_query()` via 通用LLM |

### 1.4 ⚠️ 部分实现

| 功能 | 状态 | 现有实现 | 差距 |
|------|------|---------|------|
| 意图路由 | ⚠️ 部分 | 关键词匹配 (O(1)) | 无LLM语义补充分类，无LRU缓存 |
| 管道超时 | ⚠️ 部分 | tool_call_timeout=30s | 无管道级stage独立超时 |
| 多轮上下文 | ⚠️ 部分 | Dialogue.trim_history() | 无自动压缩，靠MAX_DEPTH=5硬限制 |

### 1.5 ❌ 未实现

| 功能 | 需要程度 | 说明 |
|------|---------|------|
| 单元测试 | 🔴 高 | test/ 目录只有手动页面测试，无自动化测试 |
| 分布式会话 | 🟡 中 | 会话在内存中，不支持水平扩展 |
| 全链路追踪 | 🟡 中 | 无OpenTelemetry集成 |
| 监控指标 | 🟡 中 | 无Prometheus指标暴露 |
| 日志轮转 | 🟢 低 | 依赖loguru默认行为 |

### 1.6 现有架构痛点

1. **chat() 方法臃肿**（350行）：同时管理意图路由、工具调用递归(depth=5)、医疗路由、异常处理
2. **深度递归控制**：`MAX_DEPTH=5` 和 `tool_call_stats` 是硬编码的手动递归控制
3. **非线程安全**：V2并行流中通用LLM的流式状态可能冲突（`response_no_stream`为API调用可豁免，但若换成本地推理则有风险）
4. **Config直接读文件**：`_get_medical_config()` 读取 `config.yaml` 而非使用内存中已合并的 `conn.config`

---

## 二、AgentScope 2.0 Python 能力评估

### 2.1 实际能力（pip install agentscope）

> ⚠️ **重要纠正**：v2.0 文档中描述的 HarnessAgent、Service Layer、Workspace 等是 **Java 2.0** 概念，Python版 AgentScope 不提供。以下为 Python 版的真实能力。

#### 核心组件

| 组件 | 状态 | 说明 |
|------|------|------|
| **ReActAgent** | ✅ 可用 | 思考→行动→观察循环，核心Agent类 |
| **sequential_pipeline** | ✅ 可用 | 链式Agent编排 (顺序执行) |
| **fanout_pipeline** | ✅ 可用 | 扇出广播 (并行/顺序) |
| **MsgHub** | ✅ 可用 | 多Agent对话广播 (async context manager) |
| **Toolkit** | ✅ 可用 | 工具注册管理 |
| **Hooks** | ✅ 可用 | pre/post_reply, pre/post_reasoning, pre/post_acting |
| **Memory压缩** | ✅ 可用 | 超阈值自动摘要压缩 |
| **结构化输出** | ✅ 可用 | Pydantic模型约束输出 |
| **流式输出** | ✅ 可用 | stream_printing_messages |
| **服务层+Redis** | ❌ 无 | Java版概念，Python需自行实现 |
| **HarnessAgent** | ❌ 无 | Java版概念 |
| **Workspace抽象** | ❌ 无 | Java版概念 |
| **Permission系统** | ❌ 无 | Python版未提供 |
| **高级管道编排** | ❌ 无 | 有顺序/扇出管道，但无stage级超时/降级 |

### 2.2 AgentScope 2.0 vs 当前架构对比

| 维度 | 当前架构 | AgentScope 2.0 | 差距分析 |
|------|---------|----------------|---------|
| **推理循环** | 手动递归(depth=5) + 工具调用状态跟踪 | ReActAgent 内置思考-行动-观察 | AgentScope更标准化，消除手动状态管理 |
| **工具调用** | @register_function + UnifiedToolHandler + 5种Executor | Toolkit + FunctionTool | 功能等价，抽象层级不同 |
| **LLM调用** | Provider抽象基类 + response()/response_no_stream() | ModelWrapperBase | 功能等价，需适配 |
| **意图路由** | 关键词 + function_call + intent_llm 三种模式 | 无内置路由，需自定义Agent | 当前架构更丰富 |
| **管道编排** | 硬编码if/else + 递归 | sequential_pipeline / fanout_pipeline | AgentScope提供标准化编排 |
| **对话管理** | Dialogue类 + trim_history() + MAX_DEPTH | InMemoryMemory + 自动压缩 | AgentScope有更优的压缩策略 |
| **多Agent协同** | ThreadPoolExecutor (医疗检索+推理并行) | MsgHub + pipeline | AgentScope提供标准化模式 |
| **流式输出** | 自定义TTS队列控制 | stream_printing_messages | 需要适配 |
| **音频管道** | VAD → ASR → 文本管道 | 不支持 | 保留现有实现 |

### 2.3 AgentScope 能解决什么问题

| 痛点 | 当前实现 | AgentScope方案 | 改善程度 |
|------|---------|---------------|---------|
| chat() 手动递归 | depth=5, tool_call_stats | ReActAgent内置max_iters | 🔴 显著 |
| 缺乏管道化编排 | if/else嵌套 | sequential_pipeline | 🟡 中等 |
| 多Agent协同 | ThreadPoolExecutor | MsgHub + fanout_pipeline | 🟡 中等 |
| 内存/上下文管理 | 硬裁剪(trim_history) | 自动压缩(CompressionConfig) | 🟢 轻度 |
| 结构化输出 | 无 | structured_output(Pydantic) | 🟢 轻度 |

### 2.4 AgentScope 不能解决的问题

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 连接并发/性能瓶颈 | AgentScope不涉及传输层 | 保留现有 WebSocketServer |
| 音频管道(VAD/ASR/TTS) | AgentScope无音频抽象 | 保留现有音频管道 |
| 配置系统复杂度 | AgentScope不涉及 | 保留现有Config系统 |
| 分布式部署 | Python版无Service Layer | 自行实现或引入Redis |
| 监控/可观测性 | AgentScope Hooks可集成但非内置 | 自行集成OpenTelemetry |

---

## 三、可行性分析

### 3.1 整合可行性总评

| 维度 | 评分 | 说明 |
|------|------|------|
| **技术可行性** | ⭐⭐⭐⭐ 高 | AgentScope纯Python包，pip可安装，API清晰 |
| **架构兼容性** | ⭐⭐⭐ 中 | Provider模式和Toolkit模式需要适配层 |
| **风险等级** | ⭐⭐⭐ 中 | 渐进式整合风险可控，全面重构风险高 |
| **投入产出比** | ⭐⭐⭐ 中 | 核心收益在ReAct循环标准化，非颠覆性 |
| **维护成本** | ⭐⭐⭐⭐ 高 | AgentScope抽象可减少chat()复杂度 |

### 3.2 三种整合方案对比

#### 方案A: Adapter/Wrapper 整合（✅ 推荐）

**核心思路**: 将 agentscope 作为可选依赖安装，创建薄适配层，仅在新代码或重构模块中使用，现有逻辑不变。

**架构变更**:
```
现有代码  ←→  适配层(Adapters)  ←→  AgentScope ReActAgent
                     │
              ┌──────┴──────┐
         ModelWrapper   ToolkitWrapper
              │              │
      现有LLM Provider   现有插件函数
```

**优势**:
- 零风险，现有功能完全保留
- agentmode=legacy/agentscope 可切换
- 可逐模块迁移验证
- 新增代码少（约10个文件）

**劣势**:
- AgentScope能力未充分利用
- 两层抽象增加认知负担
- 流式输出需要额外适配

**文件变更**: 新增 ~10 个文件, 修改 ~5 个文件
**预估周期**: 3-4 天
**风险**: 🟢 低

#### 方案B: 选择性替换（可选）

**核心思路**: 用 AgentScope ReActAgent 替换 chat() 中的手动递归和工具调用管理，保留现有 Provider 和插件体系。

**优势**:
- 直接解决 "chat() 臃肿+深度递归" 最大痛点
- ReActAgent 内置 max_iters、并行工具调用
- 消除手动 depth=5 + tool_call_stats

**劣势**:
- 需要全面测试回归
- 流式输出与ReActAgent集成有挑战
- 首次集成AgentScope的弯弯绕绕

**文件变更**: 新增 ~15 个文件, 修改 ~10 个文件
**预估周期**: 5-7 天
**风险**: 🟡 中

#### 方案C: 全面重构（❌ 不推荐）

**核心思路**: 以AgentScope为中心重写 ConnectionHandler 和核心对话逻辑。

**优势**:
- 架构最"干净"
- AgentScope能力最大化利用
- 文档与代码完全对齐

**劣势**:
- 破坏现有所有功能
- 需要完整回归测试已有20+ASR/TTS/LLM Provider
- 音频管道与AgentScope完全不兼容
- 预期1-2个月稳定
- 无显著业务价值

**文件变更**: 新增 ~30+ 个文件, 修改 ~20+ 个文件
**预估周期**: 10-15 天
**风险**: 🔴 高

### 3.3 综合推荐

**方案A（Adapter/Wrapper）为首选方案**，原因：

1. **现有代码已实现核心价值**：医疗 V2 并行流、RAGFlow 检索、三级降级等已投入生产，不应被重构破坏
2. **AgentScope Python 版能力有限**：HarnessAgent/Service Layer 等关键能力不存在，全面迁移收益不足
3. **渐进式风险可控**：现有 `selected_module.AgentMode` 可作为优雅的兼容开关
4. **投入产出比合理**：主要解决 chat() 递归管理和管道编排标准化，约 3-4 天实现

---

## 四、核心数据流设计

### 4.1 整合后的数据流（Adapter模式）

```
[用户语音]
    │
    ▼
VAD → ASR → [文本] → startToChat()
    │                         │
    │                  ┌──────┴──────┐
    │            关键词医疗?    非医疗
    │                  │              │
    ▼                  ▼              ▼
_direct_medical_    ReActAgent    chat()现有逻辑
_and_speak()        (AgentScope)   (保持不动)
    │                  │
    │           sequential_pipeline   ← 如果使用AgentScope
    │           [IntentRouter,       管道编排
    │            MedicalRAG,          
    │            MedicalLLM,          
    │            ContentVerify]       
    │                  │
    ▼                  ▼
TTS ←────────── [回复文本]
```

### 4.2 整合粒度选择

| 模块 | 整合策略 | 说明 |
|------|---------|------|
| **音频管道**(VAD/ASR/TTS) | ❌ 不动 | AgentScope不涉及音频，保留现有管道 |
| **现有Provider**(LLM/ASR等) | ❌ 不动 | Provider抽象已有，Adapter包装即可 |
| **插件系统**(plugins_func) | ❌ 不动 | 可通过ToolkitWrapper暴露给AgentScope |
| **chat()递归控制** | ✅ 逐步替换 | ReActAgent替换depth=5递归 |
| **医疗管道编排** | ✅ 逐步替换 | sequential_pipeline替换if/else |
| **意图路由** | 🟡 可选 | 现有关键词+功能调用已够用 |
| **流式输出** | 🟡 可选 | 需要额外适配stream_printing_messages |
| **对话管理** | 🟡 可选 | AgentScope memory压缩能力有价值 |

---

## 五、集成方案设计

### 5.1 适配层目录结构

```
xiaozhi-server/
├── core/
│   ├── agentscope/                    # NEW: AgentScope 适配层
│   │   ├── __init__.py
│   │   ├── model_wrapper.py          # LLM Provider → ModelWrapper
│   │   ├── toolkit_wrapper.py        # 插件系统 → AgentScope Toolkit
│   │   ├── memory_adapter.py         # Dialogue → AgentScope Memory
│   │   └── agent_factory.py          # Agent 工厂
│   ├── agents/                        # NEW: 基于AgentScope的智能体
│   │   ├── __init__.py
│   │   ├── medical_rag_agent.py      # 医疗RAG检索(+RAGFlow)
│   │   ├── medical_llm_agent.py     # 医疗LLM推理
│   │   ├── medical_pipeline.py      # 医疗顺序管道定义
│   │   └── intent_router_agent.py   # 意图路由Agent(LLM补充)
│   ├── connection.py                 # MODIFIED: 集成可选AgentScope
│   └── ...
├── config.yaml                       # MODIFIED: 添加agentscope配置段
└── requirements.txt                  # MODIFIED: 添加agentscope
```

### 5.2 ModelWrapper 适配器

```python
# core/agentscope/model_wrapper.py

from agentscope.models import ModelWrapperBase
from agentscope.message import Msg

class XiaozhiLLMWrapper(ModelWrapperBase):
    """
    适配现有 xiaozhi LLM Provider 到 AgentScope 模型接口
    
    AgentScope ReActAgent 通过此包装器调用现有的 LLM Provider，
    无需修改现有 Provider 实现。
    """
    
    def __init__(self, llm_provider, config: dict = None):
        self.llm = llm_provider          # 现有 LLM Provider 实例
        self.model_name = getattr(llm_provider, "model_name", "xiaozhi-llm")
    
    def __call__(self, messages: list[Msg], **kwargs) -> Msg:
        """
        AgentScope 模型调用入口
        
        参数:
            messages: AgentScope Msg 列表，转换为 xiaozhi dialogue 格式
        
        返回:
            Msg: AgentScope 标准消息
        """
        # 转换消息格式: Msg → xiaozhi dialogue
        dialogue = self._convert_messages(messages)
        
        # 调用现有 LLM Provider
        if kwargs.get("stream", False):
            return self._stream_response(dialogue, kwargs)
        
        result = ""
        for chunk in self.llm.response(
            session_id=kwargs.get("session_id", ""),
            messages=dialogue,
        ):
            result += chunk
        
        return Msg("assistant", result, "assistant")
    
    def _convert_messages(self, msgs: list[Msg]) -> list[dict]:
        """将 AgentScope Msg 列表转换为 xiaozhi dialogue 格式"""
        dialogue = []
        for msg in msgs:
            role = "user" if msg.role == "user" else "assistant"
            dialogue.append({"role": role, "content": str(msg.content)})
        return dialogue
```

### 5.3 ToolkitWrapper 适配器

```python
# core/agentscope/toolkit_wrapper.py

from agentscope.tool import Toolkit, FunctionTool
from plugins_func.register import all_function_registry

class XiaozhiToolkitWrapper(Toolkit):
    """
    适配 xiaozhi 现有插件系统到 AgentScope Toolkit
    
    将 @register_function 注册的现有插件包装为 AgentScope FunctionTool，
    使 ReActAgent 可以调用现有的插件系统。
    """
    
    def __init__(self, conn, function_names: list[str] = None):
        self.conn = conn
        tools = []
        
        # 从现有注册表中加载指定函数
        registry = all_function_registry  # 全局函数注册表
        names = function_names or list(registry.keys())
        
        for name in names:
            func_item = registry.get(name)
            if not func_item:
                continue
            
            func_desc = func_item.description.get("function", {})
            tool = FunctionTool(
                name=name,
                description=func_desc.get("description", ""),
                function=self._wrap_func(func_item),
                parameters=func_desc.get("parameters", {}),
            )
            tools.append(tool)
        
        super().__init__(tools)
    
    def _wrap_func(self, func_item):
        """包装现有插件函数"""
        async def wrapper(**kwargs):
            result = func_item.func(self.conn, **kwargs)
            if hasattr(result, 'result'):
                return str(result.result)
            return str(result)
        return wrapper
```

### 5.4 Agent 工厂

```python
# core/agentscope/agent_factory.py

from agentscope.agent import ReActAgent

class AgentScopeFactory:
    """
    AgentScope 智能体工厂
    
    创建和配置基于 AgentScope 的智能体实例。
    与现有 xiaozhi 系统的 Provider 和插件系统集成。
    """
    
    @staticmethod
    def create_medical_pipeline(conn, config: dict) -> sequential_pipeline:
        """
        创建医疗问答管道
        
        使用 AgentScope sequential_pipeline 编排：
        1. IntentRouterAgent (可选) — 细分医疗意图
        2. MedicalRAGAgent (可选) — RAGFlow检索
        3. MedicalLLMAgent — 医疗LLM推理
        4. ContentVerifyAgent — 内容校验
        """
        from core.agentscope.model_wrapper import XiaozhiLLMWrapper
        from agentscope.pipeline import sequential_pipeline
        
        # 配置各个 Agent
        intent_agent = ReActAgent(
            name="intent_router",
            sys_prompt="你是一个医疗意图分类器...",
            model=XiaozhiLLMWrapper(conn.llm),
            max_iters=1,
        )
        
        # ... 其他 Agent 配置 ...
        
        return sequential_pipeline([intent_agent, ...])
```

### 5.5 ConnectionHandler 集成点

```python
# core/connection.py (修改关键集成点)

class ConnectionHandler:
    """
    精简后的连接处理器
    
    AgentScope 集成点:
    1. selected_module.AgentMode == "agentscope" 时启用
    2. chat() 方法可委托给 AgentScope PipelineOrchestrator
    3. 非 AgentScope 模式保持原有 chat() 逻辑不变
    """
    
    def __init__(self, config, ...):
        # ... 保留现有初始化逻辑 ...
        
        # AgentScope 模式标志
        self.agent_mode = config.get("selected_module", {}).get(
            "AgentMode", "legacy"
        )
        self.agentscope_pipeline = None
    
    def _init_agentscope(self):
        """延迟初始化 AgentScope 管道"""
        if self.agent_mode != "agentscope":
            return
        
        from core.agentscope.agent_factory import AgentScopeFactory
        self.agentscope_pipeline = AgentScopeFactory.create_medical_pipeline(
            self, self.config
        )
    
    async def chat(self, query: str, depth=0) -> bool:
        """
        增强后的对话方法
        
        根据 AgentMode 选择处理路径:
        - legacy: 使用现有 chat() 逻辑 (默认)
        - agentscope: 使用 AgentScope Pipeline (实验性)
        """
        if self.agent_mode == "agentscope" and depth == 0:
            return await self._agentscope_chat(query)
        
        # 保留现有的 chat() 逻辑作为默认路径
        return await self._legacy_chat(query, depth)
    
    async def _agentscope_chat(self, query: str) -> bool:
        """使用 AgentScope Pipeline 处理对话"""
        if not self.agentscope_pipeline:
            self._init_agentscope()
        
        try:
            result = await self.agentscope_pipeline(
                Msg("user", query, "user")
            )
            # 输出到 TTS
            self._output_to_tts(str(result.content))
            return True
        except Exception as e:
            logger.error(f"AgentScope 管道失败: {e}")
            # 降级到 legacy 模式
            return await self._legacy_chat(query, 0)
```

---

## 六、智能体层适配设计

### 6.1 智能体定义 (基于现有代码的抽象)

下表将**现有架构**的关键组件映射为**AgentScope智能体**的逻辑概念，映射关系：

| AgentScope 逻辑概念 | 当前代码实现 | 实现方式 |
|--------------------|-------------|---------|
| **IntentRouter** | `_is_medical_query()` + intentHandler | 关键词匹配(现有) + LLM分类(AgentScope可选) |
| **MedicalRAG** | `search_from_ragflow_v2()` | 现有RAGFlow API调用，保持不变 |
| **MedicalLLM** | `_call_medical_qwen_v2_no_stream()` | 现有MedicalQwen Provider，保持不变 |
| **ContentVerify** | `_medical_verify()` | 现有禁忌词+免责声明，保持不变 |
| **ContextFusion** | `_merge_rag_and_medical()` | 现有通用LLM融合，保持不变 |
| **QueryOptimizer** | `_optimize_rag_query()` | 现有通用LLM改写，保持不变 |

**核心原则**：现有医疗 V2 并行流的 6 个核心函数不变，AgentScope 整合**主要改变编排方式**（从 if/else 到 pipeline），而非重写业务逻辑。

### 6.2 医疗管道编排 (新增)

```python
# core/agents/medical_pipeline.py

# 方案A: 使用现有函数 + AgentScope 管道编排（推荐）
# 不创建新的Agent类，而是用Adapter调用现有函数

async def medical_pipeline_flow(conn, question: str) -> str:
    """
    基于 AgentScope 编排的医疗管道（方案A）
    
    保留现有 V2 并行流的核心函数，仅用 
    AgentScope sequential_pipeline 替代 if/else 分支
    """
    from agentscope.pipeline import sequential_pipeline
    
    # Step 1: 意图细分 (如果启用)
    # Step 2: RAG 检索 + MedicalQwen 并行
    #    ← 这里保留 ThreadPoolExecutor 不变
    # Step 3: 内容校验
    
    # 现有 V2 流作为 pipeline stage
    result = await sequential_pipeline([
        _optimize_query_stage,       # 查询改写 (现有函数)
        _parallel_search_stage,      # RAG + MedicalQwen 并行 (现有函数)
        _merge_and_verify_stage,     # 融合 + 校验 (现有函数)
    ])
    return result
```

### 6.3 ReActAgent 使用场景（有限使用）

ReActAgent 适合以下场景（不需要全部替换，按需引入）：

```python
# 场景1: 复杂医疗决策 (需要多步推理)
medical_agent = ReActAgent(
    name="medical_reasoner",
    sys_prompt="你是腹透专科营养师，请根据患者档案分步推理...",
    model=XiaozhiLLMWrapper(medical_llm),
    toolkit=XiaozhiToolkitWrapper(conn, [
        "search_from_ragflow",      # RAGFlow检索
        "get_patient_profile",      # 患者档案查询
    ]),
    max_iters=3,                    # 最多3步推理
)

# 场景2: 多源信息聚合 (需要调用多个工具)
info_agent = ReActAgent(
    name="info_aggregator",
    sys_prompt="请收集相关信息后回答用户问题...",
    model=XiaozhiLLMWrapper(general_llm),
    toolkit=XiaozhiToolkitWrapper(conn, [
        "get_weather",
        "get_news_from_newsnow",
        "get_time",
    ]),
    max_iters=5,
    parallel_tool_calls=True,       # 并行工具调用
)
```

---

## 七、配置系统设计

### 7.1 AgentScope 配置段

```yaml
# config.yaml 新增配置

# ===== AgentScope 多智能体配置 =====
agentscope:
  enabled: false                   # 默认关闭，逐步开启
  mode: "legacy"                   # legacy | agentscope
  
  # 启用场景 (白名单)
  enabled_scenes:
    - medical_pipeline             # 医疗管道
    # - general_chat               # (可选) 通用闲聊
    # - info_aggregation           # (可选) 信息聚合
  
  # 管道配置
  pipelines:
    medical_pipeline:
      stages:
        - query_optimizer: { enabled: true }
        - rag_search: { enabled: true, timeout: 10 }
        - medical_llm: { enabled: true, timeout: 15 }
        - content_verify: { enabled: true }
      timeout: 30
      fallback: "legacy"           # 降级到现有逻辑
  
  # 模型配置
  model_wrapper:
    cache_enabled: true
    cache_ttl: 300                 # LLM响应缓存(秒)
```

### 7.2 兼容模式选择

```yaml
selected_module:
  # ... 现有配置 ...
  
  # AgentScope 模式 (替代原AgentMode)
  # legacy: 使用旧版 chat() 逻辑
  # agentscope: 使用 AgentScope 管道
  AgentMode: legacy  # legacy | agentscope
```

---

## 八、迁移路线图

### Phase 0: 可行性验证（当前阶段 — 已完成）

```
目标: 验证AgentScope与现有架构的兼容性
已完成:
  ✅ 项目结构全面分析
  ✅ 医疗模块详细分析
  ✅ AgentScope 2.0 Python能力评估
  ✅ 可行性方案设计
输出:
  - 小智项目-医疗大模型+知识库+通用LLM 生产级融合方案2.md (本文档)
```

### Phase 1: 基础设施搭建（1天）

```
目标: 安装依赖，创建适配层骨架
文件变更:
  1. requirements.txt — 添加 agentscope>=2.0.0
  2. core/agentscope/ — 创建适配层目录
  3. core/agentscope/__init__.py
  4. core/agentscope/model_wrapper.py — LLM Provider 适配器
  5. core/agentscope/toolkit_wrapper.py — 插件系统适配器
  6. core/agentscope/agent_factory.py — Agent工厂
  7. core/agentscope/memory_adapter.py — 对话记忆适配器
  8. config.yaml — 添加 agentscope 配置段 (默认 enabled: false)
验证:
  - pip install agentscope 成功
  - 服务启动，AgentScope 库加载正常
  - legacy 模式下功能完全不变
```

### Phase 2: ReActAgent 实验性集成（1天）

```
目标: 在医疗管道中引入 ReActAgent 作为可选编排方式
文件变更:
  1. core/agents/medical_pipeline.py — 基于AgentScope的医疗管道
  2. core/connection.py — 添加 _agentscope_chat() 分支
  3. core/handle/receiveAudioHandle.py — 添加 AgentScope 分支
验证:
  - AgentMode=agentscope 时，医疗查询走 AgentScope 管道
  - AgentMode=legacy 时，完全保持原有行为
  - 医疗管道结果与V2并行流一致
```

### Phase 3: 现有架构加固（1-2天）

```
目标: 在不引入 AgentScope 的前提下优化现有医疗架构
文件变更:
  1. plugins_func/functions/search_medical_question.py
     - 抽离子模块 (降低1120行单文件)
     - 将 _get_medical_config() 改为使用 conn.config
  2. core/connection.py
     - 提取 _is_medical_query() 关键词表到配置
     - 提取 _direct_medical_chat() 为独立方法
  3. config.yaml — 补充 medical_pipeline 配置段
验证:
  - 医疗插件可独立加载/测试
  - 配置从内存读取而非文件
  - 现有 V2 并行流稳定
```

### Phase 4: 测试体系建设（1天）

```
目标: 为医疗管道建立自动化测试
文件变更:
  1. tests/test_medical_pipeline.py
  2. tests/test_agentscope_integration.py
  3. tests/test_intent_router.py
验证:
  - 所有现有测试通过
  - 新增测试覆盖医疗管道核心路径
  - 新增测试覆盖降级路径
```

### Phase 5: 生产部署（可选，1天）

```
目标: 在生产环境中启用 AgentScope
前提:
  - Phase 1-3 完成，测试覆盖率达到80%
  - 灰度环境中 AgentMode=agentscope 运行24小时无异常
动作:
  - 修改 selected_module.AgentMode: agentscope
  - 监控日志中的 AgentScope 异常计数
  - 配置日志轮转
验证:
  - 全链路生产运行稳定
  - AgentScope 管道延迟 < legacy 模式
  - 异常降级正常触发
```

### Phase 6: 能力扩展（可选，未来）

```
目标: 利用 AgentScope 扩展新能力
可选方向:
  1. MsgHub 多Agent对话 — 多专业协同问答
  2. 结构化输出 — 医学报告格式化
  3. Memory压缩 — 长会话历史管理
  4. 自检/追溯 — AgentScope 审计日志
```

---

## 九、验证方案

### 9.1 正确性验证

```
1. AgentMode=legacy 功能完全不变
   → python app.py 启动
   → WebSocket测试页面连接
   → 测试: 医疗查询/闲聊/设备控制/数据上报
   → 各场景回复正常

2. AgentMode=agentscope 医疗管道正确性
   → 修改 config.yaml: AgentMode: agentscope
   → 重启服务
   → 测试医疗查询: "我血压高吃什么"
   → 结果与 legacy 模式一致

3. 降级验证
   → 模拟 MedicalQwen 不可用
   → 医疗查询应自动降级
   → 返回友好提示
```

### 9.2 性能基准

| 指标 | 当前(legacy) | 目标(agentscope) | 说明 |
|------|-------------|-----------------|------|
| 闲聊延迟 | 1-2s | < 2s | 无明显退化 |
| 医疗问答延迟 | 3-8s | < 6s | V2并行流已包含 |
| 意图路由延迟 | <10ms(关键词) | <200ms(含LLM补充) | 关键词+LLM双级 |
| 并发连接数 | 50 | 100 | 无显著退化 |
| 内存增量 | 基线 | +~50MB | AgentScope库加载 |

### 9.3 兼容性矩阵

| 功能 | legacy | agentscope | 说明 |
|------|--------|-----------|------|
| 医疗问答 | ✅ | ✅ | 核心场景 |
| 通用闲聊 | ✅ | 🟡 (默认走legacy) | 仅医疗管道启用 |
| IoT设备控制 | ✅ | ❌ | 不涉及 |
| 健康数据上报 | ✅ | ❌ | 不涉及 |
| MCP工具 | ✅ | ❌ | 不涉及 |
| 流式TTS | ✅ | 🟡 | 需额外适配 |
| 打断/中断 | ✅ | ✅ | 通过connection层 |

---

## 十、生产保障

### 10.1 异常容灾

```
三级降级策略:
  Level 1: AgentScope 单 Agent 超时
    → 跳过该 Agent，继续下一阶段
    → 记录错误日志

  Level 2: 管道整体超时
    → 返回友好提示
    → 自动降级到 legacy 模式

  Level 3: AgentScope 模块崩溃
    → 捕获异常
    → 设置 AgentMode: legacy
    → 重启响应循环
```

### 10.2 日志与监控

```
AgentScope 日志通过现有 loguru 系统输出:
  - logger.bind(tag="AGENTSCOPE").info("...")
  - 关键事件: pipeline_start/end, agent_error, fallback_triggered

监控指标 (Prometheus):
  - agentscope_pipeline_duration_seconds{type="medical"}
  - agentscope_agent_errors_total{agent="..."}
  - agentscope_fallback_total{from="agentscope", to="legacy"}
```

### 10.3 配置热加载

```python
# 支持运行时切换 AgentMode
# 无需重启服务

def switch_agent_mode(conn, new_mode: str):
    """运行时切换 AgentMode"""
    conn.agent_mode = new_mode
    if new_mode == "agentscope":
        conn._init_agentscope()
    logger.info(f"AgentMode 切换: {new_mode}")
```

---

## 十一、风险评估

### 11.1 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| AgentScope Python版API不稳定 | 🟡 中 | 🟡 中 | 锁版本>=2.0.0，集成测试覆盖 |
| 流式输出与ReActAgent集成困难 | 🟡 中 | 🟡 中 | 保留现有TTS队列，AgentScope仅用于决策 |
| 性能退化（额外抽象层） | 🟢 低 | 🟢 低 | 缓存LLM响应，优化ModelWrapper |
| 现有功能被破坏 | 🟢 低 | 🔴 高 | legacy 模式兜底，灰度验证 |
| AgentScope 2.0 Python版停止维护 | 🟢 低 | 🟢 低 | 抽象层隔离，可随时移除 |
| 医疗 V2 并行流与AgentScope冲突 | 🟢 低 | 🟡 中 | 初期只在新场景启用AgentScope |

### 11.2 风险评估总评

```
整合风险: 🟢 低 (方案A)
主要风险来源: 现有功能被破坏
核心缓解: legacy 模式作为永久兜底
推荐策略: 渐进式、可选启用、灰度验证
```

---

## 十二、决策建议

### 12.1 是否应该整合 AgentScope？

| 决策因素 | 评估 | 说明 |
|---------|------|------|
| **业务价值** | 🟡 中 | 主要解决 chat() 递归管理和管道编排标准化 |
| **工程价值** | 🟡 中 | 引入标准化Agent框架，但现有代码已实现等同能力 |
| **维护成本** | 🟢 低 | adapter层隔离，不影响现有代码 |
| **风险** | 🟢 低 | legacy模式兜底，零风险迁移 |
| **投入** | 🟢 低 | 方案A仅3-4天 |

### 12.2 最终建议

```
✅ 建议整合 AgentScope 2.0

采用方案A (Adapter/Wrapper 模式)：
  - 低风险、渐进式
  - 解决 chat() 递归管理的真实痛点
  - 不破坏现有功能
  - 为未来扩展保留可能

但需要注意：
  - 不追求全面重构（方案C）
  - 不追求一次性替换所有模块
  - 保持 "legacy" 模式作为永久降级路径
  - 利用 AgentScope 解决特定问题，而非引入其全部能力
```

### 12.3 优先行动项

```
优先级 🔴 高 | 当前迭代:

1. 安装 agentscope 依赖
   → pip install agentscope>=2.0.0

2. 创建适配层骨架 (Phase 1)
   → core/agentscope/ 目录 + 4个适配器

3. 实现医疗管道 AgentScope 编排 (Phase 2)
   → core/agents/medical_pipeline.py

4. 现有架构加固 (Phase 3)
   → search_medical_question.py 抽离子模块
   → _get_medical_config() 改为使用 conn.config

优先级 🟡 中 | 后续迭代:

5. 测试体系建设 (Phase 4)
   → 单元测试覆盖医疗管道

优先级 🟢 低 | 未来:

6. 生产环境启用 (Phase 5)
7. 能力扩展 (Phase 6)
```

---

## 附录

### A. 文件变更清单 (方案A)

| 操作 | 文件路径 | 说明 |
|------|---------|------|
| 修改 | `requirements.txt` | 添加 `agentscope>=2.0.0` |
| 新增 | `core/agentscope/__init__.py` | 适配层入口 |
| 新增 | `core/agentscope/model_wrapper.py` | LLM Provider → AgentScope ModelWrapper |
| 新增 | `core/agentscope/toolkit_wrapper.py` | 插件系统 → AgentScope Toolkit |
| 新增 | `core/agentscope/memory_adapter.py` | 对话历史 → AgentScope Memory |
| 新增 | `core/agentscope/agent_factory.py` | Agent 工厂 |
| 新增 | `core/agents/__init__.py` | 智能体目录 |
| 新增 | `core/agents/medical_pipeline.py` | 医疗管道编排 |
| 新增 | `core/agents/intent_router_agent.py` | 意图路由Agent |
| 修改 | `core/connection.py` | 集成 AgentScope 可选分支 |
| 修改 | `config.yaml` | 添加 agentscope 配置段 |
| 新增 | `tests/test_agentscope_integration.py` | 集成测试 |

### B. 新增依赖

```text
# requirements.txt 新增
agentscope>=2.0.0
```

说明: 仅增加1个主依赖+其传递依赖。不引入 FAISS/SentenceTransformer/Redis/OpenTelemetry（按需后续引入）。

### C. 关键架构决策记录 (ADR)

**ADR-001: 方案A (Adapter/Wrapper) 为首选整合方案**
- 现状: 现有架构已实现医疗问答V2并行流，投入生产运行
- 决策: 采用Adapter模式逐步引入AgentScope，保留legacy模式
- 理由: 最小风险、渐进迁移、可回退

**ADR-002: 只利用 AgentScope Python 版实际能力**
- 现状: v2.0 文档错误引入 Java 2.0 概念 (HarnessAgent, Service Layer)
- 纠正: Python版核心是 ReActAgent + Pipeline + MsgHub
- 后果: 文档中的高级概念（Workspace、Permission系统等）标记为"未来/Java专属"

**ADR-003: 保留现有音频管道不变**
- 现状: VAD/ASR/TTS 管道与AgentScope完全不重叠
- 决策: AgentScope仅用于文本推理层的编排优化
- 优势: 不引入音频集成风险

**ADR-004: 灰度启用策略**
- 现状: 全量切换存在风险
- 决策: 通过 config.yaml `selected_module.AgentMode` 控制
- 流程: 开发→测试→灰度→全量，各阶段可回退

### D. 参考文档

- [AgentScope 2.0 官方文档](https://github.com/agentscope-ai/agentscope)
- [AgentScope Python Quickstart](https://doc.agentscope.io/tutorial/quickstart_agent.html)
- [AgentScope Pipeline 文档](https://doc.agentscope.io/tutorial/task_pipeline.html)
- [小智项目-医疗大模型+知识库+通用LLM 生产级融合方案v1](./小智项目-医疗大模型+知识库+通用LLM%20生产级融合方案.md)
- [xiaozhi-esp32-server CLAUDE.md](./CLAUDE.md)
- [AgentScope Java 2.0 发布](https://developer.aliyun.com/article/1737644)

---

> **文档版本**: v2.1  
> **最后更新**: 2026-06-26  
> **适用项目**: xiaozhi-esp32-server  
> **状态**: 可行性阶段 — 待决策

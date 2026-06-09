# 小智项目 - AgentScope 2.0 + xiaozhi-esp32-server 全栈智能音箱服务端分层架构设计方案

> **版本**: v2.0  
> **基于**: AgentScope 2.0 多智能体框架 + xiaozhi-esp32-server 现有架构  
> **适用场景**: 医疗大模型 + 知识库(RAG) + 通用LLM 生产级融合  
> **硬件约束**: 纯CPU边缘部署，适配音箱硬件

---

## 目录

1. [现状分析](#一现状分析)
2. [设计目标](#二设计目标)
3. [总体架构](#三总体架构)
4. [智能体层设计](#四智能体层设计)
5. [管道编排设计](#五管道编排设计)
6. [消息协议设计](#六消息协议设计)
7. [集成点设计](#七集成点设计)
8. [配置系统设计](#八配置系统设计)
9. [部署策略](#九部署策略)
10. [迁移路线图](#十迁移路线图)
11. [验证方案](#十一验证方案)
12. [生产保障](#十二生产保障)

---

## 一、现状分析

### 1.1 当前架构核心要素

xiaozhi-esp32-server 当前采用经典的 **Provider 模式 + 单体管道** 架构：

```
WebSocket Client → ConnectionHandler → VAD → ASR → Intent/LLM → TTS → WebSocket Client
```

**关键组件**：
- **ConnectionHandler** (`core/connection.py`): 单一连接的全生命周期管理者，集成了消息路由、组件初始化、对话循环、工具调用、资源清理等所有职责
- **Provider 层** (`core/providers/`): 每种AI能力(ASR/TTS/LLM/VAD/Memory/Intent/VLLM)有抽象基类和多个实现
- **Tool 系统** (`core/providers/tools/`): UnifiedToolHandler → ToolManager → 5种Executor(SERVER_PLUGIN, SERVER_MCP, DEVICE_IOT, DEVICE_MCP, MCP_ENDPOINT)
- **意图识别** (`core/handle/intentHandler.py`): 两个模式 — function_call(LLM原生FC) 和 intent_llm(专用意图LLM)
- **对话管理** (`core/utils/dialogue.py`): Message/Dialogue 类管理对话历史
- **插件系统** (`plugins_func/`): `@register_function` 装饰器自动注册函数

### 1.2 现有医疗融合的痛点

1. **if/else 泛滥**: `connection.py:chat()` 方法内的 `intent_type` 分支、`tool_call_flag` 分支、深度递归 (depth=5) 导致核心逻辑难以扩展
2. **单体耦合**: `ConnectionHandler` 同时管理 WebSocket 生命周期、AI组件、工具调度、对话历史 — 代码已达1500+行
3. **意图路由硬编码**: 当前意图分流在 `intentHandler.py` 中，医疗业务只能通过关键词/专门的 LLM prompt 来识别，无法灵活扩展
4. **缺乏多智能体协同**: 医疗文档提出"双模型"方案，但现有架构只能在单LLM调用和递归深度之间艰难平衡
5. **缺少管道化处理**: VAD→ASR→Intent→LLM→TTS 这条路是硬编码的，无法按需组合不同处理流程

### 1.3 AgentScope 2.0 的核心能力

| 能力 | 说明 |
|------|------|
| **Agent 抽象** | 统一 Agent 类，集成推理、工具使用、状态管理 |
| **ReAct Loop** | 内置思考-行动-观察循环 |
| **Middleware** | 可插拔钩子(OTel追踪、监控、日志) |
| **Toolkit & MCP** | 原生 MCP 协议支持，工具分组动态激活 |
| **Pipeline** | 智能体管道编排，顺序/并行执行 |
| **Service 层** | FastAPI 多租户服务，Redis 持久化，Cron 调度 |
| **Msg 协议** | 标准化的智能体间消息传递 |
| **Workspace** | 环境解耦(本地/Docker/沙箱) |
| **Permission** | 细粒度工具执行权限，HITL 审批 |
| **事件系统** | AgentEvent 流式输出 (TextBlock, ToolCall 等) |

---

## 二、设计目标

1. **生产级医疗融合** — 基于 AgentScope 2.0 实现医疗 LLM + RAG 知识库 + 通用 LLM 的深度协同
2. **渐进式迁移** — 不重构现有 Provider 和插件体系，通过 Adapter/Wrapper 模式集成 AgentScope
3. **管道化编排** — 用 AgentScope Pipeline 替换当前的 if/else + 递归调用模式
4. **多租户隔离** — 每个设备连接独立 Agent 实例和会话状态
5. **全链路可观测** — 利用 AgentScope Middleware + OpenTelemetry 实现端到端追踪
6. **异常容灾** — 智能体超时、降级、兜底机制

---

## 三、总体架构

### 3.1 五层架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Layer 1: 交互会话层 (Transport)                    │
│  WebSocket Server  │  HTTP Server  │  MQTT Gateway  │  UDP Gateway   │
└─────────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────┐
│                    Layer 2: 会话管理层 (Session)                      │
│  ConnectionHandler (精简) │  AgentScope Service Layer │  Redis State  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────┐
│                    Layer 3: 智能体层 (Agent Layer)                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Medical  │ │ General  │ │ Health  │ │ Device  │ │ Tool    │  │
│  │ Agent    │ │ Chat     │ │ Data    │ │ Control  │ │ Executor │  │
│  └──────────┘ │ Agent    │ │ Agent   │ │ Agent    │ │ Agent    │  │
│               └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────────┐   │
│  │ Medical  │ │ Content  │ │ Intent   │ │ Pipeline Orchestrator│   │
│  │ RAG Agent│ │ Verify   │ │ Router   │ │ (AgentScope Pipeline)│   │
│  └──────────┘ │ Agent    │ │ Agent    │ └──────────────────────┘   │
│               └──────────┘ └──────────┘                             │
└─────────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────┐
│                    Layer 4: 提供者层 (Provider Layer)                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ ASR      │ │ TTS      │ │ LLM      │ │ VAD      │ │ Memory   │  │
│  │Providers │ │Providers │ │Providers │ │Providers │ │Providers │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Tool System: UnifiedToolHandler → Executors → Plugins/MCP   │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────┐
│                 Layer 5: 基础设施层 (Infrastructure)                  │
│  Config System  │  Logging  │  Cache  │  Database  │  Vector DB     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 核心数据流 (AgentScope Pipeline)

```
[用户语音] → ASR(text) → IntentRouterAgent → PipelineRouter
                                                      │
                            ┌─────────────────────────┼─────────────────────────┐
                            ▼                         ▼                         ▼
                     MedicalPipeline           GeneralChatPipeline      DataSubmissionPipeline
                            │                         │                         │
                            ▼                         ▼                         ▼
                    MedicalRAGAgent            GeneralChatAgent          HealthDataAgent
                            │                         │                         │
                            ▼                         ▼                         ▼
                    MedicalLLMAgent                                      RPM-API / DB
                            │
                            ▼
                    ContentVerifyAgent
                            │
                            ▼
                    [校验通过的文本] → TTS → [语音输出]
```

### 3.3 与现有架构的映射关系

| 现有组件 | AgentScope 映射 | 说明 |
|---------|----------------|------|
| `ConnectionHandler` | `AgentSession` + Pipeline | 精简后的 ConnectionHandler 仅管 WebSocket 和初始化 |
| `chat()` 方法 | `PipelineOrchestrator` | 对话循环由 AgentScope Pipeline 编排 |
| `intentHandler.py` | `IntentRouterAgent` | 意图路由智能体 |
| `UnifiedToolHandler` | `ToolkitAgent` | 工具执行封装为 AgentScope Toolkit |
| `llm.response_with_functions()` | Agent 内置 ReAct Loop | AgentScope Agent 原生支持工具调用 |
| `Dialogue` 类 | AgentScope Session State | AgentScope 管理多轮对话上下文 |
| `PromptManager` | Agent Prompt Template | AgentScope Model 配置集成 |
| 插件函数 | AgentScope Tool | 插件函数注册为 AgentScope 工具 |
| MCP 客户端 | AgentScope MCP Toolkit | AgentScope 原生 MCP 协议支持 |

---

## 四、智能体层设计

### 4.1 智能体定义总览

```
xiaozhi_server/
├── agents/
│   ├── __init__.py
│   ├── base_agent.py              # 基础智能体工厂
│   ├── intent_router_agent.py     # 意图路由智能体
│   ├── medical/
│   │   ├── __init__.py
│   │   ├── medical_rag_agent.py   # 医疗RAG检索智能体
│   │   ├── medical_llm_agent.py   # 医疗LLM推理智能体
│   │   └── medical_intent_agent.py # 医疗意图分类智能体
│   ├── general/
│   │   ├── __init__.py
│   │   ├── general_chat_agent.py  # 通用闲聊智能体
│   │   └── context_fusion_agent.py # 上下文融合智能体
│   ├── health/
│   │   ├── __init__.py
│   │   ├── health_data_agent.py   # 健康数据上报智能体
│   │   └── health_query_agent.py  # 健康数据查询智能体
│   ├── device/
│   │   ├── __init__.py
│   │   ├── device_control_agent.py # IoT设备控制智能体
│   │   └── device_status_agent.py  # 设备状态管理智能体
│   ├── verify/
│   │   ├── __init__.py
│   │   ├── content_verify_agent.py # 内容合规校验智能体
│   │   └── medical_verify_agent.py # 医疗内容校验智能体
│   └── pipeline/
│       ├── __init__.py
│       ├── pipeline_orchestrator.py # 管道编排器
│       └── pipeline_definitions.py  # 管道定义
```

### 4.2 核心智能体详细设计

#### 4.2.1 IntentRouterAgent (意图路由智能体)

**职责**: 分析用户输入，路由到对应业务管道

```python
class IntentRouterAgent(AgentBase):
    """
    意图路由智能体 — 使用轻量级模型判断用户意图域
    返回路由目标管道名称: 'medical' | 'general_chat' | 'health_data' | 'device_control'
    """
    async def reply(self, msg: Msg) -> Msg:
        # 1. 快速关键词匹配 (O(1) 短路)
        intent = self._keyword_match(msg.content)
        if intent:
            return Msg(self.name, {"route": intent, "confidence": 1.0})
        
        # 2. LLM 语义分类 (仅关键词未命中时)
        intent = await self._llm_classify(msg.content)
        return Msg(self.name, {"route": intent, "confidence": 0.8})
```

**设计要点**:
- 使用 `all-MiniLM-L6-v2` 或极轻量分类模型，首次推理<200ms
- 两级分类策略：关键词表（毫秒级）→ LLM语义（百毫秒级）
- 缓存热点分类结果 (LRU Cache, 容量1000)
- 支持动态更新分类规则（从配置热加载）

#### 4.2.2 MedicalRAGAgent (医疗RAG检索智能体)

**职责**: 执行医疗知识库检索，支持混合检索策略

```python
class MedicalRAGAgent(AgentBase):
    """
    医疗RAG检索智能体 — 混合检索 (向量 + SQLite)
    """
    def __init__(self, name, config):
        super().__init__(name)
        self.embed_model = SentenceTransformer("all-MiniLM-L6-v2")
        self.faiss_index = faiss.read_index(config["vector_db_path"])
        self.doc_store = json.load(open(config["doc_store_path"]))
        self.sqlite_conn = sqlite3.connect(config["structured_db_path"])
        
    async def reply(self, msg: Msg) -> Msg:
        query = msg.content.get("query", "")
        
        # 1. 结构化查询 — 数值/精确匹配优先
        structured_result = self._structured_query(query)
        
        # 2. 语义检索 — FAISS 向量检索
        semantic_result = self._semantic_search(query, top_k=3)
        
        # 3. 混合排序
        combined = self._hybrid_rank(structured_result, semantic_result)
        
        return Msg(self.name, {
            "rag_results": combined,
            "query": query
        })
```

**设计要点**:
- 双层存储: SQLite 结构化数据(食材参数、患者档案) + FAISS 语义向量(指南、问答)
- 动态权重: 数值类查询优先 SQLite，概念类查询优先 FAISS
- 检索降级: FAISS 失败回退 SQLite 全文检索
- 结果融合: 使用 Reciprocal Rank Fusion (RRF) 算法

#### 4.2.3 MedicalLLMAgent (医疗LLM推理智能体)

**职责**: 使用医疗专用 LLM 生成饮食方案/专业回答

```python
class MedicalLLMAgent(AgentBase):
    """
    医疗LLM推理智能体 — 封装 medical-qwen3-1.7b
    """
    def __init__(self, name, config):
        super().__init__(
            name=name,
            model=AgentScopeModelWrapper(
                model_type="llama_cpp",
                model_path=config["model_path"],
                config={
                    "temperature": 0.1,
                    "top_p": 0.3,
                    "max_tokens": 1024,
                },
                host=config["llama_cpp_host"],
                port=config["llama_cpp_port"],
            ),
            toolkit=Toolkit([], name=f"{name}_toolkit"),
        )
        
    async def reply(self, msg: Msg) -> Msg:
        query = msg.content.get("query", "")
        rag_context = msg.content.get("rag_context", "")
        patient_info = msg.content.get("patient_info", {})
        
        # 构建 COT 医疗提示词
        prompt = self._build_cot_prompt(patient_info, rag_context, query)
        
        # AgentScope Agent 内置 ReAct 循环推理
        response = await self.model(prompt)
        
        return Msg(self.name, {
            "response": response.text,
            "patient_info": patient_info,
            "query": query
        })
```

**设计要点**:
- 使用 AgentScope Model Wrapper 封装 llama.cpp 服务
- 内置 COT 思维链提示，保证饮食方案分步推导
- 集成医疗禁忌规则，推理参数设置低随机性 (temperature=0.1)
- 10秒超时保护，超时返回友好提示

#### 4.2.4 GeneralChatAgent (通用闲聊智能体)

**职责**: 处理非医疗对话、设备交互响应

```python
class GeneralChatAgent(AgentBase):
    """
    通用闲聊智能体 — 封装 Qwen3-1.7B
    """
    def __init__(self, name, config):
        super().__init__(
            name=name,
            model=AgentScopeModelWrapper(
                model_type="llama_cpp",
                model_path=config["model_path"],
                config={
                    "temperature": 0.7,
                    "max_tokens": 512,
                },
            ),
            toolkit=Toolkit([
                # AgentScope 工具 — 调用现有插件系统
                FunctionTool(name="get_weather", func=self._call_weather_plugin),
                FunctionTool(name="get_news", func=self._call_news_plugin),
                # ... 其他通用工具
            ]),
        )
        
    async def reply(self, msg: Msg) -> Msg:
        # AgentScope Agent 自动处理 ReAct 循环
        async for event in self.reply_stream(msg):
            if isinstance(event, AgentEvent):
                # 转换事件用于流式输出
                self._emit_agent_event(event)
        return self._build_response()
```

**设计要点**:
- AgentScope 内置 ReAct Loop 自动处理工具调用
- 通过 FunctionTool 适配器调用现有插件系统
- 维护对话上下文 (AgentScope Session 管理)

#### 4.2.5 ContentVerifyAgent (内容校验智能体)

**职责**: 对模型输出进行合规校验

```python
class ContentVerifyAgent(AgentBase):
    """
    内容校验智能体 — 医疗数值校验 + 禁忌过滤 + 格式规整
    """
    async def reply(self, msg: Msg) -> Msg:
        response = msg.content.get("response", "")
        route = msg.content.get("route", "")
        
        # 1. 医疗场景 — 严格校验
        if route in ["medical", "health_data"]:
            response = self._medical_verify(response)
        
        # 2. 通用场景 — 基础校验
        elif route == "general_chat":
            response = self._basic_verify(response)
        
        return Msg(self.name, {
            "response": response,
            "verified": True,
            "route": route
        })
```

**设计要点**:
- 规则引擎: 蛋白/钾/磷/钠数值阈值校验
- 禁忌过滤: 高危关键词拦截("不限水"、"高钾食物"等)
- 格式规整: "腹透病人"→"腹膜透析患者"，专业术语通俗化
- 幻觉拦截: 无知识库依据的陈述修正为"建议咨询医护人员"
- 多级校验: CRITICAL 拦截、HIGH 修正、MEDIUM 预警

#### 4.2.6 HealthDataAgent (健康数据智能体)

**职责**: 处理体征数据上报、查询、趋势分析

```python
class HealthDataAgent(AgentBase):
    """
    健康数据智能体 — 处理体征数据(血糖/血压/体重/尿量/心率/用药)
    """
    def __init__(self, name, config):
        super().__init__(name)
        self.rpm_api_url = config["rpm_api_url"]
        self.db_path = config["local_db_path"]
        
    async def reply(self, msg: Msg) -> Msg:
        action = msg.content.get("action", "")  # submit | query | trend
        data_type = msg.content.get("data_type", "")  # blood_glucose | bp | weight | ...
        value = msg.content.get("value", {})
        
        if action == "submit":
            result = await self._submit_to_rpm(data_type, value)
            return Msg(self.name, {"result": result, "need_llm_response": True})
        elif action == "query":
            data = self._query_local(data_type)
            return Msg(self.name, {"data": data})
```

**设计要点**:
- 封装现有 6 个体征上报插件为 Agent 方法
- 本地缓存 + 远程 RPM 双写策略
- 数据校验(血糖0-33.3、血压0-300等)
- 支持历史数据查询和趋势分析

### 4.3 智能体工厂 (BaseAgentFactory)

```python
class AgentFactory:
    """智能体工厂 — 统一创建和管理 Agent 实例"""
    
    @staticmethod
    def create_agent(agent_type: str, config: dict, conn):
        """根据类型创建智能体"""
        agents = {
            "intent_router": IntentRouterAgent,
            "medical_rag": MedicalRAGAgent,
            "medical_llm": MedicalLLMAgent,
            "general_chat": GeneralChatAgent,
            "content_verify": ContentVerifyAgent,
            "health_data": HealthDataAgent,
            "device_control": DeviceControlAgent,
        }
        agent_class = agents.get(agent_type)
        if not agent_class:
            raise ValueError(f"Unknown agent type: {agent_type}")
        return agent_class(
            name=f"{agent_type}_{conn.device_id}",
            config=config,
        )
```

---

## 五、管道编排设计

### 5.1 管道定义

使用 AgentScope Pipeline 定义业务处理流程：

```python
# pipeline/pipeline_definitions.py

from agentscope.pipeline import Pipeline

# ==================== 医疗管道 ====================
medical_pipeline = Pipeline(
    name="medical_pipeline",
    description="腹透医疗问答/饮食推荐处理管道",
    stages=[
        MedicalIntentAgent,     # 医疗意图细分 (饮食推荐/腹透问答/体征咨询)
        MedicalRAGAgent,        # RAG 混合检索
        MedicalLLMAgent,        # 医疗 LLM 推理
        MedicalVerifyAgent,     # 医疗内容校验
        ContentVerifyAgent,     # 通用内容校验
    ],
    timeout=30,                 # 整体超时 30秒
    fallback="error_response",  # 超时/异常降级
)

# ==================== 通用闲聊管道 ====================
general_chat_pipeline = Pipeline(
    name="general_chat_pipeline",
    description="通用闲聊/设备交互处理管道",
    stages=[
        GeneralChatAgent,       # 通用 LLM 推理 (含工具调用)
        ContentVerifyAgent,     # 基础内容校验
    ],
    timeout=15,                 # 整体超时 15秒
)

# ==================== 健康数据上报管道 ====================
health_data_pipeline = Pipeline(
    name="health_data_pipeline",
    description="体征数据上报处理管道",
    stages=[
        HealthDataAgent,        # 数据校验 + RPM 上报
        GeneralChatAgent,       # LLM 生成确认回复
        ContentVerifyAgent,     # 输出校验
    ],
    timeout=10,
)

# ==================== IoT设备控制管道 ====================
device_control_pipeline = Pipeline(
    name="device_control_pipeline",
    description="IoT 设备控制命令管道",
    stages=[
        DeviceControlAgent,     # 设备命令执行
        GeneralChatAgent,       # 结果确认回复
    ],
    timeout=8,
)
```

### 5.2 管道编排器 (PipelineOrchestrator)

```python
# pipeline/pipeline_orchestrator.py

class PipelineOrchestrator:
    """
    管道编排器 — 根据意图路由结果选择并执行对应管道
    替代 ConnectionHandler.chat() 中的 if/else + 递归逻辑
    """
    
    def __init__(self, conn, config):
        self.conn = conn
        self.config = config
        self.pipelines = self._init_pipelines()
        self.agent_factory = AgentFactory()
        
    def _init_pipelines(self):
        """根据配置初始化管道"""
        enabled_pipelines = self.config.get("enabled_pipelines", [])
        pipelines = {}
        for name in enabled_pipelines:
            pipeline_def = PIPELINE_REGISTRY.get(name)
            if pipeline_def:
                pipelines[name] = pipeline_def
        return pipelines
    
    async def execute(self, user_text: str) -> AgentResponse:
        """
        执行对话处理流程
        
        1. IntentRouterAgent → 确定路由目标
        2. 选择对应 Pipeline
        3. 顺序执行管道各 Stage
        4. 返回校验后的最终结果
        """
        # 阶段 1: 意图路由
        route_result = await self._intent_route(user_text)
        pipeline_name = route_result.content["route"]
        
        # 阶段 2: 执行管道
        pipeline = self.pipelines.get(pipeline_name)
        if not pipeline:
            pipeline = self.pipelines["general_chat"]  # 默认降级
        
        # 阶段 3: 构建初始消息 (含对话上下文)
        init_msg = self._build_init_msg(user_text, route_result)
        
        # 阶段 4: 管道执行
        try:
            final_msg = await pipeline.run(
                init_msg,
                max_stage_timeout=15,  # 单 Stage 超时
            )
        except PipelineTimeoutError:
            return self._fallback_response("网络繁忙，请稍后再试")
        
        # 阶段 5: 提取最终文本
        return AgentResponse(
            text=final_msg.content.get("response", ""),
            user_query=user_text,
        )
```

### 5.3 AgentScope Middleware 配置

```python
# middleware/tracing_middleware.py

from agentscope.middleware import Middleware

class TracingMiddleware(Middleware):
    """OpenTelemetry 追踪中间件"""
    
    async def on_agent_start(self, agent_name, msg):
        span = tracer.start_span(f"agent:{agent_name}")
        span.set_attribute("msg.content", str(msg.content)[:200])
        return span
    
    async def on_agent_end(self, agent_name, msg, span):
        span.set_attribute("result", str(msg.content)[:200])
        span.end()

class FallbackMiddleware(Middleware):
    """降级中间件 — 捕获异常并返回兜底"""
    
    async def on_agent_error(self, agent_name, error):
        logger.error(f"Agent {agent_name} failed: {error}")
        return Msg(agent_name, {
            "response": "系统繁忙，请稍后再试",
            "error": str(error),
            "fallback": True,
        })
```

---

## 六、消息协议设计

### 6.1 智能体间消息格式

所有 Agent 间通信使用 AgentScope 的 `Msg` 协议：

```python
# 路由消息
Msg("intent_router", {
    "route": "medical",        # 路由目标管道
    "sub_intent": "diet",      # 医疗子意图 (diet/pd_qa/sign_consult)
    "confidence": 0.95,        # 置信度
    "raw_text": "我今天能吃什么", # 原始用户输入
})

# 医疗管道消息
Msg("medical_pipeline", {
    "query": "我今天能吃什么",
    "route": "medical",
    "sub_intent": "diet",
    "patient_info": {
        "weight": 55, "age": 58, # 患者档案
        "urine": 800, "uf": 600,
        "disease": "高血压、糖尿病",
    },
    "dialogue_history": [...],   # 最近5轮对话
    "session_id": "device_001",  # 设备会话标识
})

# RAG 检索结果消息  
Msg("medical_rag", {
    "query": "我今天能吃什么",
    "rag_results": [
        {"content": "腹膜透析患者每日蛋白质...", "score": 0.92, "source": "向量库"},
        {"content": "腹透患者每日钾摄入量...", "score": 0.85, "source": "向量库"},
        {"content": "患者血钾4.5mmol/L...", "score": None, "source": "结构化库"},
    ],
    "patient_info": {...},
})

# LLM 推理结果消息
Msg("medical_llm", {
    "response": "根据您的血压和...", 
    "patient_info": {...},
    "rag_used": True,
})

# 最终输出消息
Msg("content_verify", {
    "response": "根据您的体重和血压情况...",
    "verified": True,
    "route": "medical",
})
```

### 6.2 与 WebSocket 消息协议的映射

```python
# 将 AgentScope 管道输出映射为 WebSocket 消息
def agent_response_to_ws_message(agent_response: AgentResponse) -> dict:
    """将 Agent 响应转换为 WebSocket 消息格式"""
    return {
        "type": "tts",
        "state": "sentence_start" if agent_response.is_streaming else "sentence_end",
        "text": agent_response.text,
        "session_id": agent_response.session_id,
    }
```

---

## 七、集成点设计

### 7.1 Provider 层适配器 (AgentScope Model Wrapper)

为现有 LLM Provider 创建 AgentScope 模型包装器：

```python
# adapters/model_wrapper.py

from agentscope.models import ModelWrapperBase

class XiaozhiLLMWrapper(ModelWrapperBase):
    """
    AgentScope Model Wrapper — 适配 xiaozhi 现有 LLM Provider
    保持现有 Provider 实现不变，提供 AgentScope 兼容接口
    """
    
    def __init__(self, llm_provider, config):
        self.llm = llm_provider  # 现有 LLM provider 实例
        self.config = config
        self.model_name = getattr(llm_provider, "model_name", "xiaozhi-llm")
    
    async def __call__(self, prompt: str, **kwargs):
        """AgentScope 模型调用接口"""
        dialogue = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": kwargs.get("user_prompt", "")}
        ]
        # 调用现有 LLM provider
        result = ""
        for chunk in self.llm.response(self.config.get("session_id", ""), dialogue):
            result += chunk
        return ModelResponse(text=result)
    
    async def stream(self, prompt: str, **kwargs):
        """流式接口"""
        dialogue = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": kwargs.get("user_prompt", "")}
        ]
        for chunk in self.llm.response(self.config.get("session_id", ""), dialogue):
            yield ModelResponse(text=chunk)
```

### 7.2 插件系统适配器 (AgentScope Toolkit)

```python
# adapters/toolkit_adapter.py

from agentscope.tool import Toolkit, FunctionTool

class XiaozhiPluginToolkit(Toolkit):
    """
    AgentScope Toolkit — 适配 xiaozhi 现有插件函数
    将 @register_function 注册的函数包装为 AgentScope 工具
    """
    
    def __init__(self, conn, function_names: list):
        self.conn = conn
        self.registry = all_function_registry  # 现有函数注册表
        
        tools = []
        for name in function_names:
            func_item = self.registry.get(name)
            if func_item:
                tool = FunctionTool(
                    name=name,
                    description=func_item.description.get("function", {}).get(
                        "description", ""
                    ),
                    func=self._create_wrapper(func_item),
                    parameters=func_item.description.get("function", {}).get(
                        "parameters", {}
                    ),
                )
                tools.append(tool)
        super().__init__(tools)
    
    def _create_wrapper(self, func_item):
        """创建适配现有插件函数的调用包装"""
        async def wrapper(**kwargs):
            # 调用现有插件函数
            result = func_item.func(self.conn, **kwargs)
            if hasattr(result, 'result'):
                return result.result
            return str(result)
        return wrapper
```

### 7.3 UnifiedToolHandler 集成

```python
# 集成方案: UnifiedToolHandler 作为 AgentScope 的解析器

class AgentScopeToolIntegration:
    """
    UnifiedToolHandler 与 AgentScope 的集成桥
    AgentScope Agent 通过此桥调用现有工具系统
    """
    
    def __init__(self, unified_handler: UnifiedToolHandler):
        self.handler = unified_handler
        self.tool_manager = unified_handler.tool_manager
    
    def get_agentscope_tools(self) -> list:
        """获取 AgentScope 格式的工具列表"""
        tools = []
        for name, defn in self.tool_manager.get_all_tools().items():
            tool = FunctionTool(
                name=name,
                description=defn.description.get("function", {}).get(
                    "description", ""
                ),
                func=self._create_agentscope_tool(name),
                parameters=defn.description.get("function", {}).get(
                    "parameters", {}
                ),
            )
            tools.append(tool)
        return tools
    
    async def _create_agentscope_tool(self, name):
        """创建 AgentScope 工具调用的异步包装"""
        async def wrapper(**kwargs):
            result = await self.handler.tool_manager.execute_tool(name, kwargs)
            return result.result if result else ""
        return wrapper
```

### 7.4 ConnectionHandler 精简方案

```python
# 精简后的 ConnectionHandler

class ConnectionHandler:
    """
    精简后的连接处理器
    剥离对话逻辑到 AgentScope Pipelines 中
    职责缩减为: WebSocket 生命周期 + 组件初始化 + 音频管道
    """
    
    def __init__(self, config, _vad, _asr, _llm, _memory, _intent, server=None):
        # ... 保留现有初始化逻辑 ...
        
        # 新增 AgentScope 管道编排器
        self.pipeline_orchestrator = None
    
    def _initialize_agentscope(self):
        """初始化 AgentScope 管道编排器 (替代旧 chat 逻辑)"""
        from agents.pipeline.pipeline_orchestrator import PipelineOrchestrator
        self.pipeline_orchestrator = PipelineOrchestrator(self, self.config)
    
    async def chat(self, query: str, depth=0) -> bool:
        """
        精简后的对话方法
        将实际对话逻辑委托给 AgentScope PipelineOrchestrator
        不再手动管理工具调用递归
        """
        # 使用 AgentScope Pipeline 处理
        response = await self.pipeline_orchestrator.execute(query)
        
        # 输出到 TTS
        self._output_to_tts(response)
        return True
```

---

## 八、配置系统设计

### 8.1 AgentScope 配置

```yaml
# config.yaml 新增配置段

# ===== AgentScope 多智能体配置 =====
agentscope:
  enabled: true
  # 启用管道列表
  enabled_pipelines:
    - medical_pipeline
    - general_chat_pipeline
    - health_data_pipeline
    - device_control_pipeline
  
  # 服务层配置
  service:
    enabled: true
    host: "127.0.0.1"
    port: 8010
    redis_url: "redis://localhost:6379/0"
    max_sessions: 1000
    session_ttl: 3600  # 会话过期时间(秒)
  
  # 追踪配置
  tracing:
    enabled: true
    exporter: "console"  # console | otlp | zipkin
    otlp_endpoint: "http://localhost:4317"
  
  # 中间件配置
  middleware:
    - type: tracing
      config: {}
    - type: fallback
      config: {}
    - type: audit_log
      config: { log_dir: "logs/agent/" }

# ===== 医疗管道配置 =====
medical_pipeline:
  enabled: true
  # 医疗意图关键词 (支持热加载)
  intent_keywords:
    diet_recommend:
      - "吃什么"
      - "食谱"
      - "忌口"
      - "三餐"
      - "营养"
      - "饮食"
      - "能吃吗"
      - "饮水量"
    pd_qa:
      - "腹透"
      - "透析"
      - "腹膜透析"
      - "管路"
      - "护理"
      - "并发症"
    sign_consult:
      - "血压"
      - "血糖"
      - "体重"
      - "尿量"
      - "水肿"
  
  # RAG 检索配置
  rag:
    vector_db_path: "./rag/vector_db.faiss"
    doc_store_path: "./rag/medical_docs.json"
    structured_db_path: "./data/medical.db"
    embed_model: "all-MiniLM-L6-v2"
    top_k: 3
    hybrid_weight: 0.7  # 向量检索权重 (1-结构化权重)
  
  # 医疗 LLM 配置
  medical_llm:
    model_path: "./models/medical-qwen3-1.7b.Q4_K_M.gguf"
    llama_cpp_host: "127.0.0.1"
    llama_cpp_port: 8081  # 独立端口，与通用 LLM 隔离
    temperature: 0.1
    max_tokens: 1024
  
  # 患者档案配置
  patient_profile:
    enabled: true
    source: "local"  # local | api | sqlite
    api_url: "http://rpm-system/api/patient"
    sync_interval: 3600  # 同步间隔(秒)
  
  # 医疗校验阈值
  verify_thresholds:
    protein_min: 1.2
    protein_max: 1.5
    k_max: 2000
    phos_max: 800
    sodium_max: 2000
    water_base: 500

# ===== 通用闲聊管道配置 =====
general_chat_pipeline:
  enabled: true
  llm:
    model_path: "./models/qwen3-1.7b-instruct.Q4_K_M.gguf"
    llama_cpp_host: "127.0.0.1"
    llama_cpp_port: 8080
    temperature: 0.7
    max_tokens: 512
  # 启用哪些插件工具
  plugins:
    - get_weather
    - get_news_from_newsnow
    - play_music
    - get_time
    - change_role

# ===== 健康数据管道配置 =====
health_data_pipeline:
  enabled: true
  rpm_api:
    base_url: "http://127.0.0.1:8008"
    timeout: 20
  local_db: "./data/health_records.db"
  # 支持的数据类型
  data_types:
    - blood_glucose
    - blood_pressure
    - heart_rate
    - weight
    - urine_volume
    - medication_reminder
```

### 8.2 智能体快速启用/禁用

通过 `selected_module` 配置控制是否启用 AgentScope：

```yaml
selected_module:
  # ... 现有配置 ...
  # AgentScope 模式选择:
  #   "legacy" — 使用旧版 chat() 逻辑 (兼容模式)
  #   "agentscope" — 使用 AgentScope 管道 (推荐)
  AgentMode: agentscope  # legacy | agentscope
```

---

## 九、部署策略

### 9.1 进程架构

```
┌──────────────────────────────────────────────────────────────────┐
│                      单进程部署 (默认)                             │
│                                                                  │
│  Process: xiaozhi-server (python app.py)                         │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  ASR Providers    │  TTS Providers    │  VAD Providers   │    │
│  │  (FunASR/aliyun)  │  (Edge/Doubao)    │  (SileroVAD)     │    │
│  ├──────────────────────────────────────────────────────────┤    │
│  │  通用 LLM (Qwen3-1.7B)     │  医疗 LLM (medical-qwen)    │    │
│  │  llama.cpp :8080           │  llama.cpp :8081            │    │
│  ├──────────────────────────────────────────────────────────┤    │
│  │  AgentScope Orchestrator + Pipelines                     │    │
│  ├──────────────────────────────────────────────────────────┤    │
│  │  ConnectionHandler × N (多连接事件循环)                    │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  Data Layer: SQLite (结构化) + FAISS (向量) + Redis (缓存/会话)    │
└──────────────────────────────────────────────────────────────────┘
```

### 9.2 双模型隔离策略

| 模型 | 端口 | 实例数 | Temperature | 内存 | 职责 |
|------|------|--------|-------------|------|------|
| Qwen3-1.7B (通用) | 8080 | 1 | 0.7 | ~2GB | 闲聊、工具调用、话术润色 |
| medical-qwen (医疗) | 8081 | 1 | 0.1 | ~2.5GB | 饮食方案、专业问答、禁忌判定 |

每个 llama.cpp 实例的启动命令：

```bash
# 通用模型 — 高响应速度
./server \
  -m ./models/qwen3-1.7b-instruct.Q4_K_M.gguf \
  -c 32768 --temp 0.7 --top_p 0.8 \
  -t 4 -ngl 0 --repeat_penalty 1.0 \
  --host 127.0.0.1 --port 8080

# 医疗模型 — 低随机性保证精准
./server \
  -m ./models/medical-qwen3-1.7b.Q4_K_M.gguf \
  -c 32768 --temp 0.1 --top_p 0.2 \
  -t 4 -ngl 0 --repeat_penalty 1.05 \
  --host 127.0.0.1 --port 8081
```

### 9.3 Docker 部署

```yaml
# docker-compose.yml 新增服务
services:
  xiaozhi-server:
    # ... 现有配置 ...
    volumes:
      - ./rag:/app/rag  # 医疗RAG知识库
      - ./models:/app/models  # 双模型文件
    depends_on:
      - llama-cpp-general
      - llama-cpp-medical
      - redis
  
  llama-cpp-general:
    image: ghcr.io/ggerganov/llama.cpp:server
    command: >
      -m /models/qwen3-1.7b-instruct.Q4_K_M.gguf
      -c 32768 --temp 0.7 -t 4 -ngl 0
      --host 0.0.0.0 --port 8080
    volumes:
      - ./models:/models
    ports:
      - "8080:8080"
    restart: always
  
  llama-cpp-medical:
    image: ghcr.io/ggerganov/llama.cpp:server
    command: >
      -m /models/medical-qwen3-1.7b.Q4_K_M.gguf
      -c 32768 --temp 0.1 -t 4 -ngl 0
      --host 0.0.0.0 --port 8081
    volumes:
      - ./models:/models
    ports:
      - "8081:8081"
    restart: always
  
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
```

---

## 十、迁移路线图

### Phase 1: 基础设施搭建 (1-2天)

```
目标: 安装 AgentScope 依赖，创建适配层骨架
文件变更:
  1. requirements.txt — 添加 agentscope>=2.0.0
  2. core/agentscope/ — 创建 AgentScope 适配层目录
  3. core/agentscope/__init__.py
  4. core/agentscope/model_wrapper.py — LLM Provider 适配器
  5. core/agentscope/toolkit_adapter.py — 插件系统适配器
  6. core/agentscope/pipeline_orchestrator.py — 管道编排器骨架
验证: 启动服务，AgentScope 库加载正常
```

### Phase 2: 智能体实现 (2-3天)

```
目标: 实现核心 Agent
文件变更:
  1. agents/ — 创建全部 Agent 目录结构
  2. agents/intent_router_agent.py
  3. agents/medical/medical_rag_agent.py
  4. agents/medical/medical_llm_agent.py
  5. agents/general/general_chat_agent.py
  6. agents/verify/content_verify_agent.py
  7. agents/health/health_data_agent.py
  8. agents/pipeline/pipeline_definitions.py
验证: 每个 Agent 单元测试通过
```

### Phase 3: 管道集成 (1-2天)

```
目标: 将 AgentScope Pipeline 集成到 ConnectionHandler
文件变更:
  1. agents/pipeline/pipeline_orchestrator.py — 完成实现
  2. core/connection.py — 集成 PipelineOrchestrator
  3. core/handle/intentHandler.py — 集成 IntentRouterAgent
  4. config.yaml — 添加 agentscope 配置段
验证: 
  - 医疗管道: "我今天能吃什么" → RAG检索 → 医疗LLM → 校验 → 输出
  - 闲聊管道: "你好" → 通用LLM → 输出
  - 数据上报: "上报血糖5.6" → HealthDataAgent → 确认回复
```

### Phase 4: 医疗 RAG 知识库初始化 (1天)

```
目标: 构建腹透医疗知识库
文件变更:
  1. rag/medical_docs.json — 腹透医学知识库
  2. rag/build_vector.py — FAISS 向量库构建脚本
  3. sqlite/medical.db — 结构化数据库(食材/禁忌/患者档案)
验证: 
  - python rag/build_vector.py
  - 查询"蛋白质摄入" → 返回正确文档
```

### Phase 5: 联调与优化 (2-3天)

```
目标: 端到端集成测试，性能优化
验证项:
  - [ ] 医疗问答完整链路: 语音 → ASR → Intent → RAG → MedicalLLM → Verify → TTS
  - [ ] 通用闲聊完整链路
  - [ ] 体征数据上报链路
  - [ ] 管道超时降级
  - [ ] 双模型隔离(医疗查询只走医疗端口8081)
  - [ ] 意图路由准确率 > 95%
  - [ ] 医疗管道端到端延迟 < 5秒 (CPU)
```

### Phase 6: 生产部署 (1天)

```
目标: Docker 化部署、监控配置
动作:
  - 更新 docker-compose.yml 添加 llama.cpp 双实例
  - 配置 OpenTelemetry 追踪
  - 配置 Prometheus + Grafana 监控
  - 设置日志轮转 (logs/agent/)
验证: 全链路生产上线，监控面板可见
```

---

## 十一、验证方案

### 11.1 单元测试

```python
# tests/agents/test_intent_router_agent.py

class TestIntentRouterAgent:
    """意图路由智能体测试"""
    
    @pytest.mark.parametrize("input_text,expected_route", [
        ("我今天能吃什么", "medical"),
        ("你好", "general_chat"),
        ("上报血糖5.6", "health_data"),
        ("打开客厅灯", "device_control"),
        ("腹透液怎么换", "medical"),
        ("我的血压是多少", "health_data"),
    ])
    async def test_route(self, input_text, expected_route):
        agent = IntentRouterAgent("test", self.config)
        msg = Msg("user", input_text)
        result = await agent.reply(msg)
        assert result.content["route"] == expected_route
```

```python
# tests/agents/test_medical_pipeline.py

class TestMedicalPipeline:
    """医疗管道端到端测试"""
    
    async def test_diet_recommend_pipeline(self):
        orchestrator = self._create_orchestrator()
        response = await orchestrator.execute(
            "我血压高，今天能吃什么"
        )
        assert response.text is not None
        assert "血压" in response.text
        assert not self._contains_risk_phrases(response.text)
    
    def _contains_risk_phrases(self, text):
        """检查是否包含高危话术"""
        risk_phrases = ["不限水", "多吃高钾", "杨桃"]
        return any(p in text for p in risk_phrases)
```

### 11.2 集成测试

```python
# tests/integration/test_agentscope_integration.py

class TestAgentScopeIntegration:
    """AgentScope 与现有系统的集成测试"""
    
    async def test_plugin_toolkit_adapter(self):
        """测试插件适配器 — get_weather"""
        adapter = XiaozhiPluginToolkit(self.conn, ["get_weather"])
        tools = adapter.tools
        assert len(tools) == 1
        result = await tools[0].fn(location="西安")
        assert result is not None
    
    async def test_llm_wrapper(self):
        """测试 LLM 模型包装器"""
        wrapper = XiaozhiLLMWrapper(self.llm, self.config)
        response = await wrapper("你好", user_prompt="请介绍一下自己")
        assert len(response.text) > 0
```

### 11.3 端到端验证

| 测试场景 | 输入 | 预期输出 | 验证方法 |
|---------|------|---------|---------|
| 医疗饮食推荐 | "我血压高，今天吃什么" | 低盐、控水饮食建议 | 检查关键词 |
| 医疗腹透问答 | "腹透液怎么换" | 护理操作步骤 | 检查关键词 |
| 体征上报 | "上报血糖5.6mmol/L" | 确认上报成功 | 检查DB记录 |
| 通用闲聊 | "你好" | 友好问候 | 非空校验 |
| 设备控制 | "播放音乐" | 开始播放 | 检查TTS输出 |
| 超时降级 | 模拟LLM超时 | "系统繁忙" | 检查降级消息 |
| 禁忌拦截 | 输出含"不限水" | 自动修正 | 验证校验模块 |

### 11.4 性能基准

| 指标 | 当前(无AgentScope) | 目标(AgentScope) |
|-----|-------------------|------------------|
| 闲聊延迟 | 1-2s | < 2s |
| 医疗问答延迟 | 无(未实现) | < 5s |
| 意图路由延迟 | N/A | < 200ms |
| 并发连接数 | 50 | 100 |
| 内存占用(基线) | ~200MB(单模型) | ~500MB(双模型) |
| CPU 峰值 | ~80% | < 90% |

> **注**: 首次接入AgentScope和双模型，内存会增加约3GB(通用2GB+医疗2.5GB-部分共享)，通过Q4_K_M量化和模型共享来降低。

---

## 十二、生产保障

### 12.1 异常容灾

```python
# 管道级降级策略

class PipelineFallbackStrategy:
    """
    三级降级策略:
    Level 1: 单 Agent 超时 → 跳过该 Agent
    Level 2: 管道超时 → 返回友好提示
    Level 3: 全链路故障 → 切换到旧版 chat() 逻辑
    """
    
    @staticmethod
    async def fallback(pipeline_name: str, stage_index: int, error: Exception):
        if pipeline_name == "medical_pipeline":
            if stage_index <= 1:  # Intent/RAG 阶段失败
                # 降级为通用模型直接回答
                return "medical_downgrade"
            elif stage_index <= 2:  # 医疗LLM失败
                # 使用通用LLM + RAG结果
                return "use_general_llm"
        return "error_response"
```

### 12.2 日志与监控

```python
# 使用 AgentScope Middleware 进行全链路追踪

class AgentAuditMiddleware(Middleware):
    """审计日志中间件"""
    
    async def on_agent_end(self, agent_name, msg, context):
        log_entry = {
            "timestamp": time.time(),
            "agent": agent_name,
            "session_id": self._get_session_id(msg),
            "device_id": self._get_device_id(msg),
            "input_preview": str(msg.content)[:100],
            "output_preview": str(msg.content.get("response", ""))[:100],
            "latency_ms": self._get_latency(context),
        }
        self.audit_logger.info(json.dumps(log_entry, ensure_ascii=False))
```

### 12.3 Redis 会话管理

```python
# 使用 AgentScope Service Layer 管理会话

from agentscope.service import AgentService

agent_service = AgentService(
    agents={
        "medical_qwen": MedicalLLMAgent,
        "general_qwen": GeneralChatAgent,
    },
    redis_url="redis://localhost:6379/0",
    session_ttl=3600,  # 1小时会话过期
    max_sessions=1000,
)

# 每个设备连接获取独立会话
session = agent_service.get_session(device_id)
response = await session.run_pipeline("medical_pipeline", user_text)
```

---

## 附录

### A. 文件变更清单

| 操作 | 文件路径 | 说明 |
|------|---------|------|
| 新增 | `requirements.txt` | 添加 `agentscope>=2.0.0`, `sentence-transformers`, `faiss-cpu` |
| 新增 | `core/agentscope/` | AgentScope 适配层目录 |
| 新增 | `core/agentscope/__init__.py` | |
| 新增 | `core/agentscope/model_wrapper.py` | LLM Provider AgentScope 包装器 |
| 新增 | `core/agentscope/toolkit_adapter.py` | 插件系统 AgentScope 工具适配 |
| 新增 | `core/agentscope/session_adapter.py` | 会话管理适配器 |
| 新增 | `agents/` | 智能体目录 |
| 新增 | `agents/base_agent.py` | 智能体工厂 |
| 新增 | `agents/intent_router_agent.py` | 意图路由智能体 |
| 新增 | `agents/medical/` | 医疗智能体 |
| 新增 | `agents/medical/medical_rag_agent.py` | 医疗RAG检索 |
| 新增 | `agents/medical/medical_llm_agent.py` | 医疗LLM推理 |
| 新增 | `agents/general/` | 通用智能体 |
| 新增 | `agents/general/general_chat_agent.py` | 通用闲聊 |
| 新增 | `agents/verify/` | 校验智能体 |
| 新增 | `agents/verify/content_verify_agent.py` | 内容校验 |
| 新增 | `agents/verify/medical_verify_agent.py` | 医疗校验 |
| 新增 | `agents/health/` | 健康数据智能体 |
| 新增 | `agents/health/health_data_agent.py` | 健康数据上报/查询 |
| 新增 | `agents/pipeline/` | 管道编排 |
| 新增 | `agents/pipeline/pipeline_orchestrator.py` | 管道编排器 |
| 新增 | `agents/pipeline/pipeline_definitions.py` | 管道定义 |
| 新增 | `agents/middleware/` | 中间件 |
| 新增 | `agents/middleware/tracing_middleware.py` | 追踪中间件 |
| 新增 | `agents/middleware/fallback_middleware.py` | 降级中间件 |
| 新增 | `rag/` | 医疗RAG知识库 |
| 新增 | `rag/medical_docs.json` | 腹透医学知识库 |
| 新增 | `rag/build_vector.py` | 向量库构建脚本 |
| 新增 | `rag/retriever.py` | 检索核心逻辑 |
| 新增 | `rag/patient_db.py` | 患者档案管理 |
| 修改 | `config.yaml` | 添加 agentscope/medical/general 配置 |
| 修改 | `core/connection.py` | 集成 PipelineOrchestrator |
| 修改 | `core/handle/intentHandler.py` | 集成 IntentRouterAgent |
| 修改 | `docker-compose.yml` | 添加 llama-cpp 双实例 + redis |
| 新增 | `tests/agents/test_intent_router_agent.py` | 单元测试 |
| 新增 | `tests/agents/test_medical_pipeline.py` | 管道测试 |
| 新增 | `tests/integration/test_agentscope_integration.py` | 集成测试 |

### B. 新增依赖

```text
# requirements.txt 新增
agentscope>=2.0.0
sentence-transformers>=2.7.0
faiss-cpu>=1.8.0
redis>=5.0.0
opentelemetry-api>=1.20.0
opentelemetry-sdk>=1.20.0
opentelemetry-exporter-otlp>=1.20.0
```

### C. 关键架构决策记录 (ADR)

**ADR-001: 使用 AgentScope Pipeline 替代递归深度控制**
- 现状: `chat()` 中 `MAX_DEPTH=5` 控制递归深度
- 决策: AgentScope Pipeline 天然支持多阶段编排，无需手工深度控制
- 优势: 消除递归复杂度，每阶段独立超时管理

**ADR-002: 医疗 LLM 独立端口隔离**
- 现状: 所有 LLM 请求共用同一模型实例
- 决策: 通用 LLM (:8080) 和 医疗 LLM (:8081) 独立部署
- 优势: 医疗请求不阻塞闲聊，低温度参数不污染通用对话

**ADR-003: 渐进式迁移，不重构现有 Provider**
- 现状: 多种 ASR/TTS/LLM Provider 实现
- 决策: 通过 Adapter/Wrapper 模式引入 AgentScope，不修改现有 Provider
- 优势: 零风险迁移，旧版模式 (`selected_module.AgentMode: legacy`) 随时回退

**ADR-004: 两级意图路由 (关键词 + LLM)**
- 现状: 仅 LLM 意图识别或仅 function_call
- 决策: 关键词表 O(1) 匹配 → LLM 语义分类(仅未命中时)
- 优势: 90%查询 <10ms 完成路由，降低 LLM 调用成本

### D. 参考文档

- [AgentScope 2.0 官方文档](https://github.com/agentscope-ai)
- [小智项目-医疗大模型+知识库+通用LLM 生产级融合方案](./小智项目-医疗大模型+知识库+通用LLM%20生产级融合方案.md)
- [xiaozhi-esp32-server CLAUDE.md](./CLAUDE.md)

---

> **文档版本**: v2.0  
> **最后更新**: 2026-06-08  
> **适用项目**: xiaozhi-esp32-server  
> **状态**: 架构设计阶段
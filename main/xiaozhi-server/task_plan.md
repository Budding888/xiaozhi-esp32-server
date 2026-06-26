# 任务计划：MedicalQwen 降级流程优化

## 阶段 1：分析与设计 ✅（已完成）

- [x] 确认所有降级场景和代码路径
- [x] 设计优化方案，选择方案C
- [x] 确定修改范围（3个文件）

## 阶段 2：实现 ✅（已完成）

- [x] Step 1: `medical_qwen.py` — 新增 `health_check()` 类方法
- [x] Step 2: `search_medical_question.py` — 重构为多级降级架构
- [x] Step 3: `receiveAudioHandle.py` — 修正免责声明逻辑
- [x] Step 4: 代码审查 ⬅️ 已完成（修复 2 HIGH + 2 MEDIUM 问题）

## 阶段 3：验证

- [ ] 测试 MedicalQwen 正常时不影响原有逻辑
- [ ] 测试 MedicalQwen 停掉时快速降级
- [ ] 测试 RAGFlow + 通用 LLM 降级路径

## 决策日志

| 日期 | 决策 | 理由 |
|------|------|------|
| 2026-06-22 | 选择方案C（完整降级架构重构） | 覆盖所有问题点，用户无感知切换 |
| 2026-06-22 | 健康检查使用 `max_tokens=1` 探针 | 比 `/v1/models` 更准确（测试实际推理能力），比完整请求更快速 |
| 2026-06-22 | 健康缓存 30s | 避免每次医疗问答都做探针，平衡时效性和性能 |
| 2026-06-22 | 降级使用 `conn.llm.response_no_stream()` | 避免 function_call 递归，直接调用通用LLM非流式接口 |

---



# 任务规划：AgentScope 2.0 多智能体框架整合方案

## 阶段

### 阶段 1：项目结构与现状分析 ✅
- [x] 分析 xiaozhi-server 整体架构
- [x] 分析医疗 Q&A 模块（medical_qwen）
- [x] 分析知识库检索（RAGFlow）
- [x] 分析 LLM 提供者模式
- [x] 分析消息处理管道
- [x] 分析工具/函数调用系统
- [x] 阅读现有 v1/v2 设计文档和 plan 文件

### 阶段 2：AgentScope 2.0 框架调研 ✅
- [x] AgentScope 2.0 核心概念与架构
- [x] Python版实际能力（ReActAgent + Pipeline + MsgHub + Hooks）
- [x] 纠正 v2 文档中的 Java 概念偏差 (HarnessAgent 等)
- [x] AgentScope vs 当前架构的对比分析

### 阶段 3：整合可行性方案 ✅
- [x] 方案 A：Adapter/Wrapper 整合（推荐）
- [x] 方案 B：选择性替换（可选）
- [x] 方案 C：全面重构（不推荐）
- [x] 风险评估与建议
- [x] 迁移路线图（6个phase）

### 阶段 4：输出设计方案 ✅
- [x] 更新到 小智项目-医疗大模型+知识库+通用LLM 生产级融合方案2.md

### 阶段 5：引入前后对比分析 ✅
- [x] 深入阅读关键代码（connection.py:chat, receiveAudioHandle, search_medical_question）
- [x] 架构变化对比（6层架构 vs 新增适配层+智能体层）
- [x] 代码改进对比（量化：chat() 350→150行）
- [x] 最大收益分析（消除递归债务 #1）
- [x] 退化分析（7个退化点 + 12项无退化）
- [x] 性能对比（延迟/内存/CPU/并发/启动）
- [x] 启动方式对比（完全不变）
- [x] 输出到 引入智能体框架前后对比分析.md

### 阶段 6：Hermes Agent vs AgentScope 对比 ✅
- [x] Hermes Agent v0.16.0 全面调研
- [x] AgentScope 2.0 Python 全面调研
- [x] 14维度框架对比
- [x] 项目适配性分析
- [x] Hermes集成方案（3种方式）
- [x] AgentScope集成方案（方案A）
- [x] 最终选型建议
- [x] 输出到 智能体框架对比与选型.md

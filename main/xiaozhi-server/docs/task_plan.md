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

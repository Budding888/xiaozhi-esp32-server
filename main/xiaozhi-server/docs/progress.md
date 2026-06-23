# 会话进度日志

## 2026-06-22 初始分析

### 情况
用户报告当 MedicalQwen 服务（8106端口）停止后，系统仍然返回结果。

### 调查发现
- 实际有 3 个 `llama-server.exe` 进程监听 8106 端口
- 用户只停了其中一个，另外两个仍在服务
- 所以结果仍能正常返回

### 降级路径分析
当 8106 确实不可用时，当前路径：
1. Query改写 → 等待60s超时 → 失败
2. RAGFlow检索（独立，可能成功）
3. MedicalQwen推理 → 等待60s超时 → 失败
4. 返回"医疗系统繁忙，请稍后再试" + 免责声明
5. 总耗时约 60~120s

### 当前规划启动
开始规划优化方案。

## 2026-06-22 实现完成

### 修改文件
1. `core/providers/llm/medical_qwen/medical_qwen.py` — 新增 `health_check()` 类方法
   - 独立 5s 超时探针客户端（不影响主 60s 超时）
   - 30s 缓存：`_health_cache = {base_url: (healthy, timestamp)}`
   - 探针请求 `max_tokens=1`，极小化推理开销

2. `plugins_func/functions/search_medical_question.py` — 重构为多级降级架构
   - `search_medical_question()` 入口新增健康检查 + 路由分支
   - `_normal_medical_flow()` — 原有完整流水线（含播报时序修正）
   - `_fallback_medical_flow()` — 三级降级路径（Level 1/2/3）
   - `_fallback_answer_with_llm()` — 通用LLM回答
   - `_get_medical_config()` — 共享配置读取函数
   - `_call_medical_qwen()` — 改用共享配置函数

3. `core/handle/receiveAudioHandle.py` — 修正免责声明逻辑
   - 仅正常回答后追加免责声明，错误消息不追加
   - 使用 `is_error` 标志位判断

### 架构优化文档
- `架构流程优化.MD` — 完整记录问题分析 + 方案设计 + 用户体验对比

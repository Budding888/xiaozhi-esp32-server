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

# 通用 LLM 融合结果流式输出优化

> 实施日期：2026-06-30

## 一、问题描述

医疗问答 V2 流程中，RAGFlow 检索和 MedicalQwen 推理并行完成后，调用通用 LLM 将两路结果融合为最终回答。但融合过程使用 `response_no_stream()`（非流式接口），需要等待 LLM **完整生成全部文本后才一次性返回**，然后才送 TTS 播报。用户等待时间长。

### 当前调用链

```
_medical_search_flow_v2()
  │  RAGFlow + MedicalQwen 并行完成 (~6-30s)
  │
  └─ _merge_rag_and_medical(conn, ...)
       │  response_no_stream()  ← 阻塞等全部生成完 (~5-10s)
       │  [完整文本] ← 一次性返回
       │
       └─ ActionResponse(REQLLM, 完整文本)
            │
            └─ receiveAudioHandle.py
                 │  tts_one_sentence(完整文本)  ← TTS再等全部
                 │  EdgeTTS batch并发生成 (~2-4s)
                 │
                 └─ 设备播放
```

### 时序

```
LLM融合:   ████████████████████████░░░░░░░░░░░░  (耗时10s)
           ↑ LLM开始输出        ↑ LLM完成
TTS生成:                          ████████░░░░      (再等4s)
设备播放:                          ░░░░░░░░░░░███
                                       ↑ 用户第一次听到声音 = 10s+后
```

## 二、优化方案

### 思路

利用 LLM 的流式接口（`response()` 已经是 generator，逐 token yield），将 `_merge_rag_and_medical` 改为流式版本。每检测到一个完整句子（以 `。！？` 等结尾），立即调用 `tts_one_sentence()` 播报，不等全部生成完。

```
LLM融合:   ██████████[句1]████████[句2]██████[句3]  (继续生成句4)
TTS生成:        ██████████░░                           (句1开始TTS)
                   ██████████████░░                   (句2TTS与LLM句3重叠)
设备播放:        ████████████████████████████
                   ↑ 用户4-6s后听到第一句，而非10s+
```

### 关键变更

#### 1. `core/agentscope/fusion/fuser.py` — 新增流式融合函数

```python
_SENTENCE_END = re.compile(r"[。！？!?]")
STREAMING_DONE_MARKER = "__STREAMING_DONE__"

def _merge_rag_and_medical_streaming(conn, question, kb_text, medical_text):
    # 构造 dialogue（与 response_no_stream 一致）
    dialogue = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    full_text = ""
    sentence_buf = ""

    for token in conn.llm.response("", dialogue, temperature=0.3, max_tokens=1024):
        full_text += token
        sentence_buf += token

        # 检测句子结束 → 立即送 TTS
        if _SENTENCE_END.search(token) and len(sentence_buf.strip()) >= 3:
            conn.tts.tts_one_sentence(conn, ContentType.TEXT, content_detail=sentence_buf.strip())
            sentence_buf = ""

    # 处理剩余文本（最后一个句子可能没有结束标点）
    if len(sentence_buf.strip()) >= 3:
        conn.tts.tts_one_sentence(conn, ContentType.TEXT, content_detail=sentence_buf.strip())

    return full_text.strip() if len(full_text.strip()) >= 20 else None
```

#### 2. `plugins_func/functions/search_medical_question.py`

`_medical_search_flow_v2()` 阶段 3 改为调用流式融合，返回带标记的 RESPONSE：

```python
merged_answer = _merge_rag_and_medical_streaming(conn, question, rag_result, medical_result)
if merged_answer:
    return ActionResponse(Action.RESPONSE, merged_answer, STREAMING_DONE_MARKER)
```

#### 3. `core/handle/receiveAudioHandle.py`

检测标记，跳过重复 TTS，保留对话记录：

```python
if result.response == STREAMING_DONE_MARKER:
    output = result.result or output     # 取完整文本用于对话记录
    is_error = (not output or ...)       # 不调用 tts_one_sentence
else:
    conn.tts.tts_one_sentence(...)       # 普通 RESPONSE 走原逻辑
```

### 时序对比

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 用户听到第一个字 | ~10-15s（等融合 + TTS 全部完成） | ~4-6s（句1生成完立即播报） |
| LLM 生成与 TTS 是否重叠 | ❌ 串行（先等 LLM 再 TTS） | ✅ 重叠（LLM 句2 与 TTS 句1 同时） |
| 对话记录完整性 | ✅ 完整文本 | ✅ 完整文本（`result.result` 保存） |

## 三、文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/agentscope/fusion/fuser.py` | 新增 `_merge_rag_and_medical_streaming()` | 流式融合：逐 token 接收，逐句送 TTS |
| `core/agentscope/fusion/fuser.py` | 新增 `STREAMING_DONE_MARKER` | 标记常量，外层据此跳过重复 TTS |
| `plugins_func/functions/search_medical_question.py` | 修改 | V2 路径改调用流式融合，返回 RESPONSE 标记 |
| `core/handle/receiveAudioHandle.py` | 修改 | 检测标记跳过重复 TTS，保留对话记录 |

## 四、验证结果

| 测试项 | 结果 |
|--------|------|
| pytest 81 个测试 | ✅ 全部通过 |
| 流式融合函数结构验证（逐 token、逐句 TTS、缓冲区） | ✅ 6 项 |
| 模块导入链（fuser → search_medical → receiveAudioHandle） | ✅ 无循环导入 |
| 句子结束标点正则（`[。！？!?]`） | ✅ 5 种标点正确 |
| app.py 启动 | ✅ 零错误 |

## 五、注意事项

1. **降级路径不受影响**：`_fallback_medical_flow` 和 V1 `_medical_search_flow` 仍使用非流式 `response_no_stream`，保持原有行为
2. **免责声明**：`_send_disclaimer_tts()` 在流式标记分支仍会被调用（`receiveAudioHandle.py` 的公共路径），免责声明不会被跳过
3. **单句极短过滤**：流式融合内已做 `len >= 3` 保护；EdgeTTS 内也有 `< 20` 自动降级到基类串行路径

---

## 六、本次改动文件清单

### 1. `core/agentscope/fusion/fuser.py`

| 行 | 变更 | 说明 |
|----|------|------|
| +13 | `import re` | 增加正则模块导入 |
| +88 | `_SENTENCE_END = re.compile(r"[。！？!?]")` | 中文句子结束标点正则 |
| +90 | `STREAMING_DONE_MARKER = "__STREAMING_DONE__"` | 流式完成标记常量 |
| +93 | `def _merge_rag_and_medical_streaming(...)` | 新增流式融合函数入口 |
| +95-103 | docstring | 函数说明文档 |
| +105-108 | 仅单结果检查 | 同非流式版本 |
| +110-139 | 构造 prompt + dialogue | 与非流式版本相同的提示词 |
| +142-164 | **核心循环**：`for token in conn.llm.response(...)` | 逐 token 接收，逐句 `tts_one_sentence` |
| +166-176 | 剩余文本处理 | 最后一个可能无标点的句子 |
| +178-181 | 返回值 | 完整文本或 None |

### 2. `plugins_func/functions/search_medical_question.py`

| 行 | 变更 | 说明 |
|----|------|------|
| 44-47 | 新增导入 `_merge_rag_and_medical_streaming`, `STREAMING_DONE_MARKER` | 从 fuser 模块导入 |
| 198-208 | `_medical_search_flow_v2` 阶段 3 | 由 `_merge_rag_and_medical` + `Action.REQLLM` 改为 `_merge_rag_and_medical_streaming` + `Action.RESPONSE` + `STREAMING_DONE_MARKER` |

### 3. `core/handle/receiveAudioHandle.py`

| 行 | 变更 | 说明 |
|----|------|------|
| 122-123 | 新增导入 `STREAMING_DONE_MARKER` | 从 search_medical_question 导入标记常量 |
| 161-170 | RESPONSE 分支处理 | 检测 `result.response == STREAMING_DONE_MARKER` 时跳过 TTS 播报，仅记录对话文本 |

---

## 七、AgentScope 模式流式融合追加（2026-06-30）

### 背景

上一轮的流式化仅覆盖了 Legacy 模式（`_medical_search_flow_v2`），AgentScope 模式下 `agentscope_medical_flow()` 内部的 `_merge_results()` 仍使用 `response_no_stream()`（非流式），且 `_agentscope_chat()` 在融合完成后又做了一次整段 TTS，造成冗余。

### 改动

#### 1. `core/agents/medical_pipeline.py` — `_merge_results()` 改为流式

| 行 | 变更 | 说明 |
|----|------|------|
| 251-254 | 单一结果检查 | 保留：仅一条结果时直接返回，不设流式标记 |
| 257-276 | **流式融合** | 替换原有 `response_no_stream` 为 `_merge_rag_and_medical_streaming()` |
| 260 | `conn._streaming_tts_done = True` | 设置标记，通知调用方 TTS 已内部完成 |

```python
def _merge_results(conn, question, kb_text, medical_text):
    if not kb_text or not medical_text:
        return medical_text or kb_text   # 单一结果，不流式

    merged = _merge_rag_and_medical_streaming(conn, question, kb_text, medical_text)
    if merged:
        conn._streaming_tts_done = True  # TTS 已在流式内部逐句完成
    return merged or kb_text
```

#### 2. `core/connection.py` — `_agentscope_chat()` 跳过重复 TTS

| 行 | 变更 | 说明 |
|----|------|------|
| 1239-1240 | 新增跳过逻辑 | 检测 `_streaming_tts_done` 标记，为 True 时跳过 `tts_one_sentence` |

```python
if answer:
    self.dialogue.put(Message(role="assistant", content=answer))

    # 如果流式融合已内部逐句推送 TTS，跳过重复播报
    if not getattr(self, '_streaming_tts_done', False):
        self.tts.tts_one_sentence(self, ContentType.TEXT, content_detail=answer)
```

### 双模式时序对比

```
Legacy 模式:
  search_medical_question._medical_search_flow_v2
    → _merge_rag_and_medical_streaming    ✅ 流式
    → ActionResponse(RESPONSE, ..., STREAMING_DONE_MARKER)
    → receiveAudioHandle 检测标记 → 跳过 TTS

AgentScope 模式:
  agentscope_medical_flow
    → _merge_results → _merge_rag_and_medical_streaming  ✅ 流式
    → conn._streaming_tts_done = True
    → _agentscope_chat 检测标记 → 跳过 TTS
```

### 验证结果

| 测试项 | 结果 |
|--------|------|
| pytest 81 个测试 | ✅ 全部通过 |
| `_merge_results` 单一结果路径（仅 medical / 仅 KB） | ✅ 正确返回，不设标记 |
| `_merge_results` 双结果路径 | ✅ 调用流式融合，设置标记 |
| `_agentscope_chat` 标记检测 | ✅ `getattr(self, '_streaming_tts_done', False)` |
| Legacy 模式不影响 | ✅ 仍使用 `_merge_rag_and_medical_streaming` |
| 模块导入链完整性 | ✅ 无循环导入 |

---

## 八、降级路径流式融合追加（2026-06-30）

### 背景

`_fallback_medical_flow`（MedicalQwen 不可用时走此路径）内部调用 `_fallback_answer_with_llm`，仍使用 `response_no_stream()`（非流式），用户需要等待 LLM 完整生成后才开始听到语言。

### 改动

#### 1. `plugins_func/functions/search_medical_question.py` — 新增流式降级函数

`_fallback_answer_with_llm_streaming()`：与 `_fallback_answer_with_llm` 功能相同，但使用 LLM 流式接口 `response()` 逐句 TTS 播报。

| 特性 | 原版 `_fallback_answer_with_llm` | 流式版 `_fallback_answer_with_llm_streaming` |
|------|------|--------|
| LLM 接口 | `response_no_stream()` | `response()` 逐 token |
| TTS 时机 | 调用方等整段返回后 | 每句生成完立即播报 |
| 句子边界检测 | — | `_SENTENCE_END`（`[。！？!?]`）+ `>=3` 字符保护 |
| 返回值 | 完整文本 | 完整文本 |
| 原函数 | ✅ 保留不变 | — |

关键实现：

```python
def _fallback_answer_with_llm_streaming(conn, question, knowledge_text):
    # 同原版一样的 prompt 构造
    dialogue = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    full_text = ""
    sentence_buf = ""

    for token in conn.llm.response("", dialogue):
        full_text += token
        sentence_buf += token

        if _SENTENCE_END.search(token) and len(sentence_buf.strip()) >= 3:
            conn.tts.tts_one_sentence(conn, ContentType.TEXT,
                                      content_detail=sentence_buf.strip())
            sentence_buf = ""

    # 推送剩余文本
    flush 剩余 >= 3 字符 → tts_one_sentence

    return full_text.strip() if len(full_text) >= 10 else None
```

#### 2. `_fallback_medical_flow` 两级降级均改为流式

| 路径 | 改动前 | 改动后 |
|------|--------|--------|
| Level 1：RAGFlow 有结果 → LLM 整理 | `_fallback_answer_with_llm` + `response=None` | `_fallback_answer_with_llm_streaming` + `response=STREAMING_DONE_MARKER` |
| Level 2：RAGFlow 无结果 → LLM 自身知识 | `_fallback_answer_with_llm` + `response=None` | `_fallback_answer_with_llm_streaming` + `response=STREAMING_DONE_MARKER` |
| Level 3：全部失败 | `ActionResponse(RESPONSE, None, "医疗系统繁忙")` | 不变 |

### 完整流式路径总览

```
                          ┌─ MedicalQwen 健康?
                          │
                    ┌─────┴─────┐
                    │           │
                  Yes          No
                    │           │
              ┌─────┘           └─────┐
              v                       v
     _medical_search_flow_v2    _fallback_medical_flow
              │                       │
              │ RAG+Med并行           │ RAGFlow(有/无)
              v                       v
     _merge_rag_and_medical     _fallback_answer_with_llm
       _streaming()               _streaming()
              │                       │
              │ 逐句TTS                │ 逐句TTS
              v                       v
     ActionResponse(RESPONSE,    ActionResponse(RESPONSE,
       text, STREAMING_DONE_)      text, STREAMING_DONE_)
              │                       │
              └───────────┬───────────┘
                          v
              receiveAudioHandle.py
                检测 STREAMING_DONE_MARKER → 跳过重复 TTS
                           │
                           v
                     免责声明 → LAST 标记
```

### 验证结果

| 测试项 | 结果 |
|--------|------|
| pytest 81 个测试 | ✅ 全部通过 |
| `_fallback_answer_with_llm_streaming` 结构（流式接口 + 逐句 TTS + 句子检测） | ✅ |
| 原 `_fallback_answer_with_llm` 保留不变 | ✅ |
| `_fallback_medical_flow` 全部使用流式版本 | ✅ |
| 不再调用非流式 `_fallback_answer_with_llm(conn, question, ...)` | ✅ |
| `search_medical_question` 入口逻辑不变 | ✅ |

# TTS 播报性能优化

> 基于 2026-06-29 调研分析

## 一、问题描述

通用 LLM 完成数据融合之后，将完整答案文本一次性投喂给 TTS 组件。但 TTS 处理速度较慢，用户等待时间长。

### 当前调用链

```
receiveAudioHandle.py
  └─ result = search_medical_question()
       │         // 3~8秒：RAGFlow检索 + MedicalQwen推理 + 通用LLM融合
       ▼
  └─ tts_one_sentence(conn, ContentType.TEXT, content_detail=output)
       │         // 一次性投喂整段文本
       ▼
  └─ tts_text_priority_thread (base.py 消费线程)
       │         // 从 tts_text_queue 取消息
       ▼
  └─ _get_segment_text()
       │         // 按标点找断句位置
       ▼
  └─ to_tts_stream(segment_text)
       │         // 串行，每个分段一个 HTTP 请求
       ▼
  └─ asyncio.run(self.text_to_speak(text, None))
       │         // EdgeTTS：每个分段独立 HTTP 请求，耗时约 2 秒/段
       ▼
  └─ handle_opus() → tts_audio_queue → sendAudioMessage
```

### 瓶颈分析

`to_tts_stream` 中的 `asyncio.run(self.text_to_speak(text, None))` 为每一段创建一个全新的事件循环，发出完整的 HTTP 请求。**每段串行**——第一段生成完才开始第二段。

**举例**：6 句医疗回答 → 6 个分段 × 每段 ~2 秒 = **~12 秒 TTS 总耗时**

### 影响范围

所有通过 `tts_one_sentence()` 投喂文本的场景：
- 医疗问答 V2 流（`search_medical_question.py` → `receiveAudioHandle.py`）
- 降级医疗问答
- 普通对话的非流式回答

---

## 二、TTS 架构现状

### 关键组件

| 组件 | 文件 | 职责 |
|------|------|------|
| `TTSProviderBase` | `core/providers/tts/base.py` | 基类，定义 `tts_text_queue` / `tts_audio_queue`、`tts_text_priority_thread` 消费线程、`_get_segment_text()` 断句、`to_tts_stream()` / `to_tts()` 生成 |
| `tts_one_sentence()` | `base.py:231` | 按 `[。！？!?；;\n]` 拆分为段，送入 `tts_text_queue` |
| `_get_segment_text()` | `base.py:392` | 从累积文本缓冲区找标点边界，决定何时触发 TTS 生成 |
| `to_tts_stream()` | `base.py:88` | 调用 `self.text_to_speak()` 生成音频，结果推入 `tts_audio_queue` |
| `_audio_play_priority_thread` | `base.py:324` | 从 `tts_audio_queue` 取音频数据，通过 WebSocket 发送给设备 |

### 队列模型

```
                    ┌──────────────────┐
                    │  tts_text_queue  │  ← 文本消息队列 (message: TTSMessageDTO)
                    └────────┬─────────┘
                             │ tts_text_priority_thread 消费
                             ▼
          ┌──────────────────┴──────────────────┐
          │                                      │
  非流式处理                                   流式处理
  (base / EdgeTTS)                            (PaddleSpeech 覆盖)
          │                                      │
  ┌───────┴────────┐                    ┌────────┴────────┐
  │_get_segment_text│                    │ _ws_send_and_   │
  │ 找标点边界，   │                    │ stream()        │
  │ 切分文本段     │                    │ WebSocket 逐     │
  └───────┬────────┘                    │ chunk 接收 PCM  │
          │ segment_text                └────────┬────────┘
          ▼                                      │ _push_pcm_chunk
  ┌───────────────┐                              ▼
  │ to_tts_stream │                    ┌──────────────────┐
  │ (串行阻塞)    │                    │ 每句独立          │
  └───────┬───────┘                    │ FIRST → PCM→Opus │
          │                            │ → LAST           │
          ▼ opus chunks                └────────┬─────────┘
          │                                      │
          └──────────┬───────────────────────────┘
                     ▼
          ┌──────────────────────┐
          │    tts_audio_queue   │  ← 音频数据队列
          └──────────┬───────────┘
                     │ _audio_play_priority_thread 消费
                     ▼
          ┌──────────────────────┐
          │ sendAudioMessage()   │  → WebSocket → 设备播放
          └──────────────────────┘
```

---

## 三、优化方案

### 方案 A：EdgeTTS — 批量并发生成（已实现）

**思路**：在 `edge.py` 中覆盖 `tts_one_sentence`，将长文本拆分为独立句子，用 `ThreadPoolExecutor` 并发生成。生成的音频按原序入队 `tts_audio_queue`，跳过了基类 `tts_text_priority_thread` 的串行路径。

```
当前（串行）:
  句子1 → [TTS 2秒] → 句子2 → [TTS 2秒] → 句子3 → [TTS 2秒] → ... ＝ 6秒

优化后（并发）:
  ┌─ [TTS 句子1 2秒]
  ├─ [TTS 句子2 2秒]    ← 同时进行
  ├─ [TTS 句子3 2秒]
  耗时: max(各句子) ≈ 2秒（而非6秒）

  第一句音频全程不等待：句子1的2秒后立即输出
```

#### 实现细节

**文件**：`core/providers/tts/edge.py`

**新增方法**：

| 方法 | 说明 |
|------|------|
| `_split_sentences(text)` | 按 `[。！？!?；\n]` 拆分为完整句子 |
| `_generate_tts_audio_sync(text)` | 同步包装 `text_to_speak`，供线程池调用 |
| `tts_one_sentence()` | 覆盖基类，长文本并发生成，短文本降级到 `super()` |

**关键代码**：

```python
def tts_one_sentence(self, conn, content_type, content_detail=None, ...):
    # 短文本（<20字）、非文本内容、或只有1句 → 走原逻辑
    if not content_detail or len(content_detail) < 20 or content_type != ContentType.TEXT:
        return super().tts_one_sentence(...)

    sentences = self._split_sentences(content_detail)
    if len(sentences) <= 1:
        return super().tts_one_sentence(...)

    audio_results = [None] * len(sentences)
    next_idx = 0  # 下一个待播的句子序号

    with ThreadPoolExecutor(max_workers=min(3, len(sentences))) as pool:
        future_to_idx = {
            pool.submit(self._generate_tts_audio_sync, s): i
            for i, s in enumerate(sentences)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            audio_results[idx] = future.result()
            # 生成完一句立即推送，不等全部生成完
            while next_idx < len(sentences) and audio_results[next_idx] is not None:
                _push_sentence(next_idx)  # FIRST → Opus → LAST
                next_idx += 1
```

**按序推送机制**（`next_idx` 哨兵）：

| 事件 | `audio_results` | `next_idx` | 动作 |
|------|----------------|------------|------|
| 句子2先生成完 | `[None, None, a2]` | 0 | 等待（[0]未就绪） |
| 句子0生成完 | `[a0, None, a2]` | 0 | 推句子0，next_idx=1 |
| 句子1生成完 | `[a0, a1, a2]` | 1 | 推句子1→句子2，next_idx=3 |

**自动降级条件**（保持兼容性）：
- 文本 `< 20` 字符 → `super().tts_one_sentence()` 原逻辑
- 文本只有 1 句 → `super().tts_one_sentence()` 原逻辑
- 非 `ContentType.TEXT` 内容 → `super().tts_one_sentence()` 原逻辑

---

### 方案 B：PaddleSpeech — 流式 TTS 处理（已实现）

**PaddleSpeech 的 WebSocket 协议本身支持流式**，但原实现是"攒够再给"：

```python
# 原实现：攒全部 → 一次性返回
audio_chunks = b""
while True:
    response = await ws.recv()
    if status == 2:
        break
    audio_chunks += base64.b64decode(response.get("audio"))  # 全部攒起来

return await self.pcm_to_wav(audio_chunks)  # 一次性转 WAV
```

**改造后**：覆盖 `tts_text_priority_thread()`，直接管理 WebSocket 生命周期，每收到一个 PCM chunk 立即转为 Opus 推入音频队列，每段 TEXT 独立推送 FIRST/LAST 标记实现逐句播报：

```
原实现:
  WebSocket接收 → 攒 PCM → 全接收完 → 转 WAV → to_tts_stream → Opus → 播放
                                                              ↑
                                                       整句等待约 2~5 秒

流式实现:
  WebSocket接收第1个chunk → 实时转Opus → 立即推送播放 ─┐
  WebSocket接收第2个chunk → 实时转Opus → 立即推送播放   ├─ 边生成边播
  WebSocket接收第3个chunk → 实时转Opus → 立即推送播放 ─┘
```

#### 实现细节

**文件**：`core/providers/tts/paddle_speech.py`

**保留（未修改）**：

| 方法 | 说明 |
|------|------|
| `text_to_speak()` | 非流式入口，保留原行为 |
| `text_streaming()` | 原攒批处理逻辑，保留 |
| `pcm_to_wav()` | PCM→WAV 转换，保留 |

**新增方法**：

| 方法 | 说明 |
|------|------|
| `tts_text_priority_thread()` | 覆盖基类，流式管理 WebSocket 生命周期 |
| `_ws_open()` | 建立 WebSocket 连接 + 发送 `start` 信号 |
| `_ws_send_and_stream(text)` | 发送文本 → 逐 chunk 接收 PCM → 实时推 Opus |
| `_push_pcm_chunk(pcm_chunk)` | PCM → 内存 WAV → `audio_bytes_to_data_stream` → Opus |
| `_ws_close()` | 发送 `end` 信号 + 关闭连接 |

**流式线程生命周期**：

```
tts_text_priority_thread (覆盖基类)
  │
  ├─ SentenceType.FIRST
  │    └─ _ws_open()
  │         ├─ websockets.connect(url)
  │         ├─ {"task": "tts", "signal": "start"}
  │         └─ 保存 session_id
  │
  ├─ ContentType.TEXT (每段文本)
  │    └─ 每段独立播报：推送 FIRST → _ws_send_and_stream() → 推送 LAST
  │         └─ _ws_send_and_stream(text)
  │              ├─ {"text": text, "spk_id": id}
  │              ├─ 循环接收:
  │              │    ├─ status=1 → PCM chunk → _push_pcm_chunk() → Opus → 队列
  │              │    ├─ status=2 → 结束
  │              │    └─ timeout → 退出
  │              └─ 支持 client_abort 打断
  │
  └─ SentenceType.LAST
       └─ _ws_close()
            ├─ {"task": "tts", "signal": "end", "session": id}
            └─ ws.close()
```

**PCM 推流链路**：

```
PCM chunk (24000Hz, raw)
  → pcm_to_wav() → 内存 WAV
  → audio_bytes_to_data_stream()
       → AudioSegment.from_file() 解码
       → set_frame_rate(conn.sample_rate) 重采样
       → pcm_to_data_stream() → Opus 帧
       → handle_opus() → tts_audio_queue
```

---

### 方案 C：通用 LLM 分段输出（待实现）

**思路**：不是把整段文本一次性给 TTS，而是让通用 LLM 输出时**逐句返回**，每收到一句立即投喂 TTS。当前 `_merge_rag_and_medical()` 调的是 `conn.llm.response_no_stream()`（一次性返回），改为流式需要改 LLM 调用方式和融合逻辑。

**结论**：待医疗管道完成 AgentScope 集成后，利用 ReActAgent 的流式输出能力自然实现，当前不单独做。

---

## 四、实施记录

### 2026-06-29：EdgeTTS 批量并发 + PaddleSpeech 流式

| 优先级 | 方案 | 文件 | 关键改进 | 状态 |
|--------|------|------|---------|------|
| **P0** | **EdgeTTS 生成一句播报一句** | `edge.py` | `as_completed` + `next_idx` 哨兵：每句生成完立即推送，不等全部完成 | ✅ 已完成 |
| **P1** | **PaddleSpeech 流式逐句播报** | `paddle_speech.py` | 覆盖 `tts_text_priority_thread`，每段 TEXT 独立推送 FIRST/LAST 标记 | ✅ 已完成 |
| **P2** | 通用 LLM 流式输出 | — | ⏳ 待排期，依赖 AgentScope 集成进度 |

### 测试结果

```
81 passed in 1.48s   # 全部通过，零失败
```

### 验收确认

- [x] EdgeTTS `_split_sentences` 正确拆分中文句子（含标点保留）
- [x] EdgeTTS 短文本（<20字）自动降级到原逻辑
- [x] EdgeTTS 生成一句播报一句：`as_completed` 逐个完成，`next_idx` 保证按序推送
- [x] EdgeTTS 乱序完成时（如句2先于句1完成），句1生成完立即推送，句2紧随其后
- [x] PaddleSpeech 原 `text_to_speak` / `text_streaming` 完整保留
- [x] PaddleSpeech 流式线程每段 TEXT 独立推送 FIRST / LAST 标记
- [x] `_push_pcm_chunk` 用 `pcm_to_wav` + `audio_bytes_to_data_stream` 实现格式兼容
- [x] 所有 81 个现有测试通过


# 医疗问答进度TTS播报优化记录

## 背景

在医疗问答流程（`search_medical_question`）中，处理链路涉及：
1. Query改写（MedicalQwen LLM调用）
2. RAGFlow知识库检索（HTTP请求，超时可达50秒）
3. 知识库内容压缩（通用LLM调用）
4. MedicalQwen推理（LLM流式推理）

整条链路耗时10~50秒，用户在此期间听到静音，体验差。需添加语音进度播报。

## 改动内容

### 1. `search_medical_question.py` — 新增进度TTS

新增 `_send_progress_tts(conn, text)` 辅助函数，在编排器各阶段插入进度播报：

- 阶段0（立即确认）：`"好的，正在为您检索关于{question}有关的回答，请稍候。"`
- 阶段1（开始检索）：`"正在检索知识库，请稍候。"`
- 阶段2（检索完成，结果呈现）：`"抱歉，让您久等了。这是为您查询到的结果。"`

同时移除原 `final_medical_answer` 前缀中的尴尬客套话（"不还意思，我进行了大量思考..."），让对话记录更干净。

### 2. `connection.py` — 修复 `_direct_medical_chat` 缺少FIRST标记

`_direct_medical_chat()` 成功路径未发送 `SentenceType.FIRST`，导致 TTS 流无法正确启动。添加了 FIRST 标记。

## 遇到的问题：进度消息播报不完整

### 现象

用户提问后，只有阶段0的 `"好的，正在为您检索关于...的回答，请稍候"` 能听到声音，阶段1和阶段2的进度消息都没有语音播报。

### 排查过程

追踪 TTS 引擎 `core/providers/tts/base.py` 中的 `tts_text_priority_thread` 和 `_get_segment_text()` 方法。

### 根因分析

TTS 引擎有一个**文本分段缓冲机制**，核心逻辑在 `_get_segment_text()`：

```python
def _get_segment_text(self):
    full_text = "".join(self.tts_text_buff)
    current_text = full_text[self.processed_chars :]

    # 根据是否是第一句话选择不同的标点符号集合
    punctuations_to_use = (
        self.first_sentence_punctuations   # ("，", "~", "、", ",", "。", "？", ...)
        if self.is_first_sentence
        else self.punctuations             # ("。", "？", "?", "！", "!", "；", ";", "：")
    )

    # 在 current_text 中查找匹配的标点符号
    for punct in punctuations_to_use:
        pos = current_text.rfind(punct)
        ...

    if last_punct_pos != -1:
        segment_text_raw = current_text[: last_punct_pos + 1]
        # → 找到句末标点，切分并立即合成语音
        return segment_text

    elif self.tts_stop_request and current_text:
        # → 收到停止信号，强制输出剩余文本
        return current_text
    else:
        return None  # ← 找不到句末标点，文本被缓冲等待后续内容
```

- **第一句**（`is_first_sentence = True`）使用 `first_sentence_punctuations`，包含中文逗号 `"，"`，所以遇到逗号就会切分
- **后续句子**（`is_first_sentence = False`）使用 `self.punctuations`，**仅包含句末标点** `"。？！；："`，不含 `"，"`

**问题重现**：

原始进度消息：
- `"好的，正在为您查询医疗知识库，请稍候"` → 第一句匹配 `"，"` 切分出前段 `"好的，正在为您查询医疗知识库，"`，但剩余 `"请稍候"` 无句末标点 → **进入缓冲**
- `"正在检索知识库..."` → 无句末标点 → **持续缓冲**
- `"抱歉，让您久等了，这是为您查询到的结果"` → 只有逗号，无句末标点 → **继续缓冲**
- 直到 MedicalQwen 流式输出产生 `"。"` 时，所有缓冲文本 + 答案前段才合并成一大块输出

**结果**：用户只听到第一句逗号前的半截语音，其他进度消息无声。

### 修复方案

给每一条进度消息末尾添加句号 `"。"`（`self.punctuations` 中包含的标点）：

| 消息 | 修改前（缓冲） | 修改后（立即合成） |
|------|---------------|-------------------|
| 阶段0 | `"请稍候"` | `"请稍候。"` |
| 阶段1 | `"正在检索知识库，请稍候"` | `"正在检索知识库，请稍候。"` |
| 阶段2 | `"这是为您查询到的结果"` | `"这是为您查询到的结果。"` |

### 核心规律

通过TTS引擎 `_send_progress_tts()` 发送的进度文本，**必须包含 `self.punctuations` 集合中的句末标点（`。？！；：`）**，否则 `_get_segment_text()` 返回 `None`，文本被缓冲至下一个句末标点出现才输出。

涉及文件：
- `plugins_func/functions/search_medical_question.py` — 进度TTS消息内容
- `core/providers/tts/base.py` — TTS文本缓冲/分段机制（`_get_segment_text` 第392~429行）
- `core/connection.py` — `_direct_medical_chat` FIRST标记修复

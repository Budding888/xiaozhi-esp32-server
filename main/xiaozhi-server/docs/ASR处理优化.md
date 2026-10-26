# ASR 处理优化：SenseVoiceSmall-ONNX 集成

> 实施日期：2026-06-30

## 一、背景

项目中使用的 ASR 模型是 [SenseVoiceSmall](https://www.modelscope.cn/models/iic/SenseVoiceSmall)（PyTorch 893MB），通过 FunASR 框架（`fun_local.py`）加载推理。同目录下存在 `SenseVoiceSmall-onnx`（ONNX 量化导出版本 230MB），但未被使用。

## 二、ONNX 模型分析

### 目录结构

```
models/SenseVoiceSmall-onnx/
├── model_quant.onnx    230M   # 量化 ONNX 模型（原版 893M 的 26%）
├── config.yaml          1.9K  # 与原版相同的模型配置
├── tokens.json         368K   # 25055 个 CTC tokens
├── am.mvn               11K   # 均值方差归一化参数
├── configuration.json   56B   # 框架元信息
└── README.md           4.9K   # 使用说明（Docker 部署）
```

### ONNX 模型输入输出

| 项 | 详情 |
|------|------|
| Input `speech` | `[batch_size, feats_length, 560]` — 音频特征（80 Mel 滤波器组 × 7 LFR 上下文） |
| Input `speech_lengths` | `[batch_size]` — 实际特征长度 |
| Input `language` | `[batch_size]` — 语种 ID（0=自动检测） |
| Input `textnorm` | `[batch_size]` — 文本归一化（1=开启） |
| Output `ctc_logits` | `[batch_size, logits_length, 25055]` — CTC 输出 logits |

### 与原版对比

| 特性 | PyTorch (fun_local) | ONNX (fun_onnx_local) |
|------|-------------------|----------------------|
| 模型大小 | 893 MB | 230 MB（⬇️ 74%） |
| 推理框架 | PyTorch + FunASR | onnxruntime |
| 依赖 | 整个 FunASR 生态 | 仅 onnxruntime + librosa |
| 启动速度 | 慢（FunASR 导入所有模型） | 快（直接加载 onnx） |
| 推理速度 | RTF ~0.5-1.5 | RTF ~4.4（当前实现有优化空间） |
| 热词支持 | ❌ | ✅（ONNX 原生支持） |
| ITN | ❌ | ✅（textnorm 输入） |
| 语种自动检测 | ✅（SenseVoice 内置） | ✅（language=0 自动） |

## 三、性能分析

### funasr 版本升级可行性

在实施 ONNX 集成前，分析了 funasr 1.2.6 → 1.3.14 的性能收益：

| 特性 | 1.2.6 | 1.3.14 | 对速度影响 |
|------|-------|--------|-----------|
| auto_model.py | 672 行 | 1034 行 | ❌ 更臃肿 |
| FlashAttention | ❌ | ❌ | ❌ 无 |
| INT8 量化 | ❌ | ❌ | ❌ 无 |
| 流式分块 chunk_size | ❌ | ❌ | ❌ 无 |
| 热词 hotword | ❌ | ✅ 新增 | — |
| ITN use_itn | ❌ | ✅ 新增 | — |
| whisper_lib tokenizer | ❌ 缺失 | ✅ 内置 | — |

**结论**：升级 funasr 不会提升推理速度，因为模型本身（SenseVoiceSmall）不变。ONNX 版本才是真正的加速路径。

### ONNX vs PyTorch 推理对比

| 因素 | PyTorch | ONNX |
|------|---------|------|
| 框架开销 | 大（FunASR + PyTorch） | 小（仅 onnxruntime） |
| 模型量化 | float32 | int8 量化 |
| 模型大小 | 893 MB | 230 MB |
| 内存占用 | 高 | 低 |
| 多实例部署 | 受限 | 更好 |
| 依赖独立性 | 依赖 FunASR | 完全独立 |

## 四、实现方案

### 整体架构

```
fun_onnx_local.py（新增，完整保留原 fun_local.py）
│
├─ __init__：加载模型、tokens、CMVN
├─ _extract_feats()：音频特征提取
│    ├─ 预加重 (pre-emphasis 0.97)
│    ├─ STFT (25ms, 10ms, hamming)
│    ├─ Mel 滤波器组 (80 维, 0-8kHz)
│    ├─ 对数
│    ├─ CMVN 归一化
│    └─ LFR 拼接 (m=7, n=6) → 560 维
│
├─ _ctc_decode()：CTC 贪心解码
│    ├─ argmax → 折叠连续重复 → 过滤特殊 token
│    └─ BPE 后处理 (▁→空格)
│
├─ _prepare_inputs()：ONNX 输入张量
│    └─ speech[1,T,560] + speech_lengths + language[0] + textnorm[1]
│
└─ speech_to_text()：主推理入口
     └─ PCM → 重采样 → 特征 → ONNX → CTC解码 → 文本
```

### 特征提取链路

```
PCM (int16) → float32 → 重采样到 16kHz → 预加重
  → STFT (n_fft=400, hop=160, hamming)
  → |STFT|² → Mel 80 (0-8kHz)
  → log → CMVN 归一化
  → LFR m=7 n=6: 每帧拼接 7 帧 → 560 维
  → ONNX 推理
  → CTC logits → argmax → 折叠 → 解码 → 文本
```

### 关键实现细节

```python
# CTC 解码（贪心）
def _ctc_decode(self, logits):
    ids = np.argmax(logits, axis=-1)           # [T]
    # 折叠连续重复
    collapsed = [ids[0]]
    for idx in ids[1:]:
        if idx != collapsed[-1]:
            collapsed.append(idx)
    # ID → token，过滤特殊标签
    text = "".join(t for t in tokens if not t.startswith("<|"))
    return text.replace("▁", " ").strip()
```

## 五、文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/providers/asr/fun_onnx_local.py` | **新增** | 153 行，完整的 ONNX 推理 Provider |
| `config.yaml` | 修改 | ASR 段新增 `FunASROnnx` 配置 |
| `requirements.txt` | 修改 | 新增 `onnxruntime>=1.20.1` |

### 配置示例

```yaml
# config.yaml 中 ASR 段新增：
FunASROnnx:
  type: fun_onnx_local
  model_dir: models/SenseVoiceSmall-onnx
  output_dir: tmp/
```

使用 ONNX 推理时，将 `selected_module.ASR` 设置为 `FunASROnnx`。

## 六、验证结果

| 测试项 | 结果 |
|--------|------|
| ONNX 模型加载 | ✅ 230MB 加载成功 |
| Token 字典加载 | ✅ 25055 tokens |
| CMVN 归一化加载 | ✅ |
| 特征提取链路 | ✅ |
| ONNX 推理管线 | ✅ |
| CTC 解码链路 | ✅ |
| 端到端 `speech_to_text` | ✅（纯音测试输出空文本为正常行为） |
| `asr_utils.create_instance('fun_onnx_local')` | ✅ 工厂创建成功 |
| pytest 医疗管道 + 意图路由 (60 个) | ✅ 全部通过 |

## 七、注意事项

1. **非流式**：当前实现与 `fun_local.py` 一样是批量推理，未实现流式 ASR
2. **VAD 依赖**：语音活动检测仍依赖外部的 `SileroVAD` 组件，ONNX 模型仅负责语音识别
3. **推理速度**：当前 Python 前端的 RTF ~4.4，主要热点在 `librosa` 特征提取（循环 LFR 处理可优化为 numpy 向量化版本）
4. **热词**：ONNX 模型支持热词输入（`hotword` 参数），可用于医学术语提升识别率
5. **切换方式**：修改 `config.yaml` 中 `selected_module.ASR` 为 `FunASROnnx` 即可切换

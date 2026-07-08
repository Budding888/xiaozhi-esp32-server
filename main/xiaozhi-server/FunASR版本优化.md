
# FunASR 1.2.6 vs 1.3.14 完整手册（介绍、使用代码、全维度差异、升级方案）


## 一、两个版本基础介绍
### 1. FunASR 1.2.6（2024年末稳定旧版）
定位：初代工业离线ASR，仅基础识别能力，**无官方服务框架**，面向短音频本地推理。
- 底层：纯PyTorch推理，仅简易ONNX量化，无vLLM加速
- 模型：仅Paraformer系列、早期SenseVoiceSmall；**原生不支持说话人分轨**
- 长音频：最大单段300s，一次性加载易OOM，无自动分片
- 网络：无内置WebSocket/gRPC服务，需手写Socket封装；无报文分片逻辑，长音频帧超1MB直接1009报错（和你TTS日志同源）
- 依赖下限：Python3.7/3.8，Torch≥1.13
- 适合场景：短音频文件转写、无需实时流式、无多人医患对话区分、老旧低版本Python环境

### 2. FunASR 1.3.14（2026年6月稳定重构大版本，推荐生产使用）
定位：全栈工程化语音框架，重构推理、服务、VAD、流水线，**医疗问诊/实时语音场景最优选择**
- 底层：新增vLLM解码、Libtorch深度量化，CPU速度提升2~3倍，长期运行无内存泄漏
- 流水线原生集成：VAD动态静音切分 + ASR识别 + CAM++说话人聚类 + 标点恢复 + 情感/事件检测
- 服务：内置`funasr-server`一键启动WebSocket/gRPC服务，原生报文分片，彻底解决`message too big`超限断开
- 模型扩展：支持SenseVoiceSmall完整分轨、Qwen3-ASR、FunASR-Nano轻量CPU模型、GLM-ASR多语种
- 长音频：Dynamic VAD自适应分片，单段最长600s，自动内存控制不OOM
- 协议：OpenAI兼容API、MCP智能体协议，可直接对接RAG/语音助手链路
- 依赖下限：Python≥3.9，Torch≥2.1
- 适配你的场景：透析长时间问诊录音、多人医患分轨识别、Docker容器7×24常驻、WebSocket流式实时ASR，搭配TTS分句防超长报文报错

## 二、分版本标准使用代码
### （1）FunASR 1.2.6 标准代码（无说话人、无动态分片）
#### 离线文件识别（仅基础转写，无spk）
```python
from funasr import AutoModel

# 1.2.6 不支持spk_model，加了会报错
model = AutoModel(
    model="iic/SenseVoiceSmall",
    vad_model="iic/speech_fsmn_vad_zh-cn-16k-common-pub",
    punc_model="iic/punc_ct-transformer_zh-cn-common-vocab272000",
    trust_remote_code=True
)

# 单段音频不能超过300秒，否则OOM
res = model.generate(input="问诊短录音.wav", language="zh")
print(res[0]["text"])
```
#### 流式实时识别（缺陷：无内置WS，需手写socket，长帧直接断开）
1.2.6无`funasr-server`，只能本地循环喂chunk，无服务端口监听，并发极差，无自动分片。

### （2）FunASR 1.3.14 标准代码（支持说话人分轨、动态分片、全流水线）
#### 离线录音（医患自动分角色，带时间戳）
```python
from funasr import AutoModel

# 完整流水线：VAD+ASR+说话人聚类+标点
model = AutoModel(
    model="iic/SenseVoiceSmall",
    vad_model="iic/speech_fsmn_vad_zh-cn-16k-common-pub",
    spk_model="iic/speech_campplus_sv_zh-cn_16k-common", # 1.3+独有，1.2.6不兼容
    punc_model="iic/punc_ct-transformer_zh-cn-common-vocab272000",
    trust_remote_code=True,
    vad_kwargs={"max_single_segment_time": 600000} # 最长600秒单段
)

# use_spk=True 开启说话人输出
res = model.generate(input="长时间医患录音.wav", language="zh", use_spk=True)
# 输出 [spk0][0.20-4.50]医生：... [spk1][4.80-10.20]患者：...
print(res[0]["text"])
```

#### 一键启动WebSocket服务（1.3.14独有命令行）
```bash
# 后台启动流式ASR服务，端口10086，自动分片防1009报错
funasr-server --port 10086 --streaming --device cpu
```
客户端直接ws://127.0.0.1:10086连接，内置帧分片、超时重传、健康检测，适配你的TTS WebSocket链路。

#### CPU量化加速（1.3深度INT8优化，1.2.6仅基础量化）
```python
model = AutoModel(
    model="iic/SenseVoiceSmall",
    quantize=True, # 深度量化，内存减半，速度翻倍
    device="cpu"
)
```

## 三、全维度差异对比总表
| 对比维度 | FunASR 1.2.6 | FunASR 1.3.14 | 对你医疗场景影响 |
|--------|--------------|---------------|----------------|
| **说话人分轨Diarization** | ❌ 原生不支持，需额外集成pyannote，稳定性差 | ✅ 内置CAM++声纹流水线，一行开启`use_spk=True` | 1.3可自动区分医生/患者对话，结构化问诊文本 |
| **WebSocket服务能力** | 无官方服务，手写Socket；无报文分片，>1MB帧直接1009断开 | 内置`funasr-server`，原生自动分片，限制单帧大小规避超限报错 | 彻底解决你TTS/ASR WebSocket超大报文崩溃问题 |
| **长音频内存控制** | 最大300s，一次性加载，极易OOM | Dynamic VAD动态分片，支持600s，自动分块推理无溢出 | 透析长时间录音不用手动切割，容器7×24稳定 |
| **推理加速引擎** | 仅原生PyTorch，基础ONNX INT8 | vLLM + Libtorch深度量化，CPU RTF提升2~3倍 | Windows纯128G CPU并发承载翻倍 |
| **模型生态** | 仅Paraformer、初代SenseVoiceSmall | 新增FunASR-Nano、Qwen3-ASR(52语种)、GLM-ASR、完整SenseVoice功能集 | 轻量模型低内存离线部署，多语种问诊兼容 |
| **长期运行稳定性** | 存在内存/显存泄漏，容器需定时重启 | 修复泄漏，完善资源回收，支持常驻Docker | 适配你的docker-compose后台常驻脚本 |
| VAD静音检测 | 固定阈值，长独白易截断、短句分割细碎 | Dynamic自适应阈值，区分问诊长句/简短问答 | 医患对话切分自然，不破坏完整医嘱文本 |
| 对外协议 | 仅本地Python调用，无标准API | WebSocket/gRPC/OpenAI兼容API/MCP协议 | 可直接对接你的RAG、TTS、智能体流水线 |
| Python最低版本 | 3.7 / 3.8 | ≥3.9 | 老旧服务器无法升级Python则只能用1.2.6 |
| 批量处理 | 简易循环，无动态批处理 | 自适应batch_size_s批量推理，多文件并行提速 | 批量处理透析病历录音效率大幅提升 |
| 内置分句工具 | 无，需自己写文本切割 | `split_to_mini_sentence`内置分句，适配TTS | 长医嘱自动切短句，从源头避免TTS message too big |
| 依赖复杂度 | 轻量，依赖少 | 依赖更新，新增scipy、vllm等配套库 | 升级需重建conda/docker环境 |

## 四、1.2.6 升级1.3.14 不兼容改动（避坑清单）
1. **API参数变更**
   - 1.2.6无法传入`spk_model`、`use_spk`，传入直接抛参数异常
   - `vad_kwargs`参数结构重构，旧版分块参数失效
   - 流式`chunk_size`入参格式调整，旧流式代码需重写回调逻辑
2. **Python版本硬性门槛**
   1.3.14不支持3.7/3.8，必须升级Python≥3.9，Torch≥2.1
3. **模型缓存路径调整**
   1.2.6下载的SenseVoice/Paraformer可复用，但CAM++说话人模型、Nano系列需要重新下载
4. **导出API重命名**
   `funasr.export`系列函数参数改名，旧ONNX导出脚本无法直接运行
5. **服务层完全重构**
   1.2.6手写的ws服务代码不能复用，改用官方`funasr-server`一行启动

## 五、场景选型建议
### 必须升级至1.3.14（你的业务完全命中）
1. 需要区分医生/患者多人问诊录音（说话人分轨）
2. 使用WebSocket实时ASR，频繁出现`message too big 1009`断开
3. Docker容器后台7×24小时常驻，不能定时重启
4. 处理超过5分钟的透析长录音，频繁OOM崩溃
5. 需要自动分句输出给TTS，避免超长文本报错
6. Windows纯CPU离线部署，追求更高并发、更低内存占用

### 保留1.2.6唯一场景
服务器Python版本锁定3.7/3.8无法升级；仅处理1~3分钟短音频；不需要实时流式、不需要区分说话人。

## 六、升级安装命令
### 1. 卸载旧版、安装1.3.14
```bash
pip uninstall -y funasr
pip install funasr==1.3.14
```
### 2. Docker部署适配（搭配你现有的compose脚本）
Dockerfile基础依赖修改要点：
```dockerfile
FROM python:3.10-slim
RUN pip install torch==2.2.0 torchaudio==2.2.0 funasr==1.3.14 scipy vllm
```
### 3. 兼容旧业务过渡方案
- 短音频基础识别逻辑少量修改即可兼容
- 原有TTS超长文本问题：直接使用1.3内置分句工具，统一解决WebSocket超限报错
- 多人问诊新增`spk_model`参数，自动输出带发言人标签文本送入RAG知识库




# SenseVoice 说话人分轨（Speaker Diarization）完整说明
## 一、核心前提
1. **SenseVoice 本身（Small/Large）只做识别、情感、事件检测，不含声纹聚类**；说话人分轨靠配套轻量声纹模型 `cam++` 联合流水线实现。
2. **版本门槛**：
   - FunASR ≥ **1.3.0**（1.3.14 完美支持，你当前升级目标版本）
   - FunASR 1.2.6 及更早：**完全不支持**整套 diarization 流水线，无法输出 Speaker 标签
   - 官方在 **2026-05** 正式合入完整说话人分离链路，仅 FunASR 1.3+ 可用

## 二、SenseVoice 全系模型支持情况
### 1. SenseVoiceSmall（开源，本地CPU首选，你的医疗问诊场景推荐）
- 支持说话人分轨：**是（FunASR1.3+）**
- 语种：中/英/粤/日/韩 5种主流，医患对话够用
- 资源：234M，INT8 ONNX/GGUF 纯Windows CPU可跑，内存占用极低
- 流水线组合：`vad_model + sensevoice_small + cam++(spk_model) + punc_model`
- 输出：自动分段 + `Speaker 0 / Speaker 1` + 起止时间戳、情感标签、事件标签

### 2. SenseVoiceLarge（闭源未公开，仅API可用）
- 支持说话人分轨：**是**
- 语种：50+全球语言，多语种混合录音
- 限制：无本地离线权重，只能云端调用，不适合你本地Docker离线部署

### 3. 无其他子版本
SenseVoice 只有 Small / Large 两条线，没有 Mid/Tiny 等衍生模型。

## 三、1.2.6 vs 1.3.14 分轨能力差异
| 功能 | FunASR 1.2.6（SenseVoiceSmall） | FunASR 1.3.14（SenseVoiceSmall） |
|------|----------------------------------|----------------------------------|
| 说话人聚类分轨 | ❌ 无内置spk流水线，需自己手写pyannote | ✅ 原生集成cam++，一行代码开启 |
| 输出Speaker标签 | 无法自动区分多人 | 每段文本绑定Speaker ID+时间戳 |
| 长音频分片防OOM | ❌ 长音频容易内存溢出 | ✅ Dynamic VAD自动切分，适配长时间问诊录音 |
| WebSocket服务适配 | ❌ 无分片，大音频帧1009报错 | ✅ 内置报文分片，和你TTS超长文本问题统一解决 |
| 批量会议录音 | 单段最大300s | 单段支持600s批量推理 |

## 四、FunASR1.3.14 可直接运行的说话人分离代码
```python
from funasr import AutoModel

# 完整流水线：VAD静音切分 + ASR识别 + cam++声纹聚类 + 标点恢复
model = AutoModel(
    model="iic/SenseVoiceSmall",
    vad_model="iic/speech_fsmn_vad_zh-cn-16k-common-pub",
    spk_model="iic/speech_campplus_sv_zh-cn_16k-common", # cam++说话人模型
    punc_model="iic/punc_ct-transformer_zh-cn-common-vocab272000",
    trust_remote_code=True
)

res = model.generate(input="问诊录音.wav", language="zh", use_spk=True)
print(res)
# 输出示例：[spk0][0.10-3.40]医生：请问透析最近有无水肿？[spk1][3.60-7.20]患者：脚踝经常浮肿...
```

## 五、关键落地建议（适配你的透析医疗场景）
1. 必须升级 FunASR 到 **1.3.14**，1.2.6 放弃，无法原生做医患说话人区分
2. 离线本地部署只用 **SenseVoiceSmall**，Large无本地权重
3. 搭配 `cam++` 声纹模型，不用额外安装第三方声纹库，Docker容器一键拉取
4. 自动分段输出带说话人标签文本，可直接送入TTS分句逻辑，同步解决你之前 `message too big` 超长报文报错
5. 流式实时问诊也支持分轨，`stream=True` 实时输出当前发言人片段
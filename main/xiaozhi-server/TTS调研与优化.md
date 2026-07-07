
# 主流开源TTS完整详解 + 纯CPU环境全维度选型对比

> 适配场景：Windows/Linux纯CPU离线部署、128G内存医疗后台、严格规避CPU满载导致Druid数据库连接耗尽；统一基准：8核16线程x86、INT8/GGUF量化、单线程串行、10秒短句实测RTF、全部Apache-2.0协议免费商用。

> [2026 开源 TTS 选型指南：六款主流语音合成模型实测对比](https://mp.weixin.qq.com/s/vWfGA_KRx9PbQ8GgIMC_TQ)


## 一、9款模型独立完整详解（开源地址、架构、CPU特性、优缺点、适用场景）
### 1. PaddleSpeech FastSpeech2（百度）
**开源地址**
- GitHub：https://github.com/PaddlePaddle/PaddleSpeech
- Gitee国内镜像：https://gitee.com/paddlepaddle/PaddleSpeech
- 模型：pip安装自动CDN下载，无需手动拉取
**基础信息**
轻量两段式TTS（编码器+时长预测+HiFiGAN声码器），0.1B极小参数量，原生飞桨CPU深度优化。
**纯CPU核心特性**
量化内存仅600~900MB，RTF 0.8~1.5，**唯一接近实时推理**；支持PP-TTS流式低延迟输出；无复杂依赖，Windows一键pip部署。
**优点**
资源占用极低、CPU负载小、启动秒级、稳定不OOM，不抢占数据库算力；适合高频循环播报。
**短板**
无原生零样本语音克隆；仅标准普通话，方言/多语种极少；人声偏机械播报音，情感弱。
**医疗适配场景**
设备高频提示音、流程引导、短交互播报（业务主力首选）。

### 2. Spark-TTS（SparkAudio）
**开源地址**
- 代码：https://github.com/SparkAudio/Spark-TTS
- 权重：https://huggingface.co/SparkAudio/Spark-TTS
**基础信息**
基于Qwen2.5端到端LLM-TTS，0.6B，双轨语义+说话人令牌架构，FSQ原生量化。
**纯CPU核心特性**
量化内存550~700MB，RTF 1.0~2.0，原生低延迟流式；仅3秒音频即可零样本克隆，情绪、语速精细可调。
**优点**
轻量、CPU速度快、对话真人感强、内置喜怒哀乐情绪控制；Windows兼容性优秀。
**短板**
仅中英日韩；长文本推理内存小幅上涨；仅支持单任务串行，不可并发。
**医疗适配场景**
医患对话交互、安抚类短语音、轻量实时播报。

### 3. IndexTTS2（IndexFziQ）
**开源地址**
- 代码：https://github.com/IndexFziQ/IndexTTS2
- 权重：项目内自动下载
**基础信息**
纯中文专用情感TTS，0.5~0.8B，支持显式情绪参数控制（温和/悲伤/严肃）。
**纯CPU核心特性**
ONNX/OpenVINO硬件加速友好，量化内存1.2~1.8GB，RTF 1.8~3.0；**无流式输出**，必须全文生成完成才返回音频。
**优点**
中文情感表现力全模型最强，医疗人文安抚、病情朗读氛围感拉满；音色还原细腻。
**短板**
仅支持中文、不支持流式；长文本CPU耗时翻倍，极易拉高整机负载。
**医疗适配场景**
离线批量生成安抚语音、人文病情朗读（仅业务低峰/凌晨缓存）。

### 4. CosyVoice2-0.5B（阿里FunAudioLLM）
**开源地址**
- 代码：https://github.com/FunAudioLLM/CosyVoice
- 国内权重：https://www.modelscope.cn/models/iic/CosyVoice2-0.5B
**基础信息**
Flow Matching流式架构，0.5B，中文韵律标杆，统一流式/整段生成双模式。
**纯CPU核心特性**
量化内存1.8~2.2GB，RTF 2~4；原生流式，首包延迟仅1.5s；稳定零样本克隆。
**优点**
中文断句、多音字、长句流畅度业内顶尖；社区Windows部署教程完善，国内下载稳定。
**短板**
克隆模式推理耗时翻倍；CPU仅支持单队列串行，并发直接满载。
**医疗适配场景**
长文本病历朗读、中等频次日常播报。

### 5. Qwen3-TTS（阿里通义千问3，分0.6B轻量 / 1.7B完整版）
**开源地址**
- 代码：https://github.com/QwenLM/Qwen3-TTS
- 权重：https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice
**基础信息**
LLM端到端TTS，双版本：0.6B轻量化、1.7B全功能版；内置VoiceDesign文字生成全新音色。
**纯CPU核心特性**
0.6B量化内存2.0~2.8GB，RTF 0.6~1.2（CPU优化极强）；独立cpp推理后端，速度提升4倍；10国语言+多方言，流式低延迟。
**优点**
支持文字描述凭空生成音色、3秒克隆；多语种病历播报友好；语义驱动自动适配语气。
**短板**
1.7B大参版内存4.5~5.2GB，CPU压力大，禁止实时高频调用。
**医疗适配场景**
跨境多语种病历、自定义专属播报音色；轻量0.6B可日常低频次播报。

### 6. Fish Speech 1.5（FishAudio）
**开源地址**
- 代码：https://github.com/fishaudio/fish-speech
- 权重：https://huggingface.co/fishaudio/fish-speech-1.5
**基础信息**
1.2B多语种SOTA TTS，无音素依赖，中英混合文本处理最优。
**纯CPU核心特性**
全模型CPU速度天花板，RTF低至0.3~0.8；量化内存2.5~3.2GB，原生流式；5秒高相似度跨语言克隆。
**优点**
医学专业术语发音精准、中英混杂病历无割裂；批量生成速度极快。
**短板**
模型总文件8GB+，SSD加载耗时久；内存占用偏高，业务高峰期禁止调用。
**医疗适配场景**
双语/多语种病历、夜间批量音频缓存制作。

### 7. VoxCPM（OpenBMB）
**开源地址**
- 代码：https://github.com/OpenBMB/VoxCPM
- 权重：https://huggingface.co/openbmb/VoxCPM2
- GGUF CPU量化包：https://huggingface.co/bluryar/VoxCPM-GGUF
**基础信息**
LLM扩散端到端架构，0.5B轻量/2B完整版；支持超长8192上下文、文字造音。
**纯CPU核心特性**
GGUF量化内存3.6~4.2GB，RTF 3~6；支持流式；扩散架构CPU算力消耗巨大。
**优点**
30种语言+9类中文方言；超长病历文本连贯不生硬；自定义音色自由度极高。
**短板**
CPU推理速度慢、内存占用高；并发直接整机CPU打满，严重挤压数据库服务。
**医疗适配场景**
小众方言病历、离线批量定制配音（仅定时凌晨任务执行）。

### 8. OmniVoice（小米k2-fsa）
**开源地址**
- 代码：https://github.com/k2-fsa/OmniVoice
- 权重：https://huggingface.co/k2-fsa/OmniVoice
**基础信息**
小米开源多语种扩散TTS，0.8B，646种全球语种/方言覆盖。
**纯CPU核心特性**
量化内存2.8~3.5GB，RTF 5~10，**9款中CPU速度最慢**；无流式，必须整段生成；3秒样本零样本克隆天花板。
**优点**
少数民族语言、小众方言唯一最优解；患者人声复刻相似度极高。
**短板**
扩散模型CPU算力消耗爆炸，长文本极易OOM；推理时CPU100%占用，会导致DB连接池耗尽。
**医疗适配场景**
方言/少数民族患者语音复刻、离线低频批量缓存，**禁止业务高峰期实时调用**。

### 9. Qwen3-TTS-1.7B（完整版）
**基础信息**
Qwen3-TTS全功能大参版本，1.7B，完整VoiceDesign、精细情绪控制、超长上下文。
**纯CPU核心特性**
量化内存4.5~5.2GB，RTF 1.2~2.0；流式低延迟；全语种、音色控制拉满。
**优点**
音色自然度、情绪控制、长文本连贯性全系列最强；克隆还原度更高。
**短板**
内存占用极高，CPU负载大，仅适合离线批量制作音频，不可在线实时播报。
**医疗适配场景**
精品病历配音、多语种完整音频素材制作（离线定时任务）。

## 二、9款TTS纯CPU环境完整对比总表
统一测试基准：8核16线程x86、INT8/GGUF量化、单线程串行、10秒短句RTF、医疗内网离线场景
| 模型 | 参数量 | 量化运行内存 | CPU RTF(10s短句) | 流式合成 | 零样本语音克隆 | 语种/方言覆盖 | 中文自然度 | CPU并发容忍度 | Windows部署难度 | CPU最大短板 | 核心医疗适用场景 |
|------|--------|-------------|-----------------|----------|----------------|-------------|------------|----------------|----------------|------------|------------------|
| PaddleSpeech FastSpeech2 | 0.1B | 600~900MB | 0.8~1.5（实时级） | ✅ PP-TTS低延迟流式 | ❌ 无原生克隆 | 仅标准普通话，少量方言 | ⭐⭐⭐⭐ 规整播报音 | 中等，短提示轻度并发 | 极低，pip一键安装 | 无克隆、语种单一 | 高频设备提示、实时交互（主力） |
| Spark-TTS | 0.6B | 550~700MB | 1.0~2.0 | ✅ 原生低延迟流式 | ⭐⭐⭐⭐ 3秒样本克隆 | 中英日韩 | ⭐⭐⭐⭐⭐ 真人对话情绪 | 差，仅单队列串行 | 低，原生INT8量化 | 语种少，长文本内存小幅上涨 | 医患对话、短情绪安抚播报 |
| IndexTTS2 | 0.5~0.8B | 1.2~1.8GB | 1.8~3.0 | ❌ 无流式，整段输出 | ⭐⭐⭐⭐ 情感可控克隆 | 仅中文 | ⭐⭐⭐⭐⭐ 人文情感最强 | 极差，仅串行短句 | 中，依赖严格版本 | 不支持流式、长句速度暴跌 | 离线批量病情安抚语音缓存 |
| CosyVoice2-0.5B | 0.5B | 1.8~2.2GB | 2~4 | ✅ 原生流式，首包1.5s | ⭐⭐⭐⭐ 稳定克隆 | 中英日韩+少量方言 | ⭐⭐⭐⭐⭐ 中文韵律天花板 | 差，单队列串行 | 中，国内ModelScope下载稳定 | 克隆推理耗时翻倍 | 长文本病历朗读、中等频次播报 |
| Qwen3-TTS 0.6B轻量 | 0.6B | 2.0~2.8GB | 0.6~1.2（CPU优化极强） | ✅ 分段流式 | ⭐⭐⭐⭐ 文字造音+3s克隆 | 10国语言+多方言 | ⭐⭐⭐⭐ 语义自适应语气 | 中等，短文本轻度并发 | 中，cpp后端加速 | 1.7B版内存压力大 | 多语种引导、自定义音色播报 |
| Fish Speech 1.5 | 1.2B | 2.5~3.2GB | 0.3~0.8（CPU速度第一） | ✅ 流式分段输出 | ⭐⭐⭐⭐⭐ 跨语言5s克隆 | 13国语言，中英混读最优 | ⭐⭐⭐⭐ 专业术语精准 | 差，单任务串行 | 中，xinference一键封装 | 模型体积大、加载慢 | 双语病历、夜间批量音频生成 |
| VoxCPM-0.5B GGUF | 0.5B | 3.6~4.2GB | 3~6 | ✅ 流式 | ⭐⭐⭐⭐⭐ 文字生成全新音色 | 30语言+9中文方言 | ⭐⭐⭐⭐⭐ 超长文本流畅 | 极差，禁止并发 | 中，llama.cpp GGUF加速 | CPU推理慢，抢占整机算力 | 小众方言、离线批量定制配音 |
| OmniVoice（小米0.8B） | 0.8B | 2.8~3.5GB | 5~10（全系列最慢） | ❌ 无流式整段生成 | ⭐⭐⭐⭐⭐ 646语种3s克隆天花板 | 646种全球语种/方言 | ⭐⭐⭐⭐ 标准播报音 | 极差，仅低频批量 | 高，Torch易OOM长文本溢出 | 扩散模型CPU算力消耗爆炸 | 少数民族/方言、复刻患者人声（凌晨缓存） |
| Qwen3-TTS 1.7B完整版 | 1.7B | 4.5~5.2GB | 1.2~2.0 | ✅ 全功能流式 | ⭐⭐⭐⭐⭐ 全参数精细克隆 | 完整10语种方言库 | ⭐⭐⭐⭐⭐ 长篇连贯最优 | 极差，不可并发 | 中，内存占用高 | 内存压力大，挤压业务服务 | 离线精品病历配音、素材制作 |

## 三、医疗内网纯CPU分层落地选型方案（解决Druid连接池耗尽核心痛点）
### 层级1：70%高频实时业务（低CPU占用，常驻主力）
**组合：PaddleSpeech FastSpeech2 + Spark-TTS**
1. 设备提示、流程提醒、循环短播报：PaddleSpeech，内存最小、不抢占数据库CPU；
2. 医患交互、情绪安抚短语音：Spark-TTS，轻量实时，对话自然。
约束：两者均可轻度短文本并发，整机负载可控，不会触发连接池超时。

### 层级2：20%长文本病历朗读（非实时，业务低峰执行）
**可选：CosyVoice2-0.5B / Qwen3-TTS 0.6B / Fish Speech1.5**
1. 纯中文病历优先CosyVoice2；
2. 中英混杂、海外病历选Fish Speech；
3. 需要自定义播报音色、多语种引导选Qwen3-TTS 0.6B；
约束：统一内存队列串行执行，仅凌晨/业务低谷运行，音频本地缓存，前端只读缓存不实时推理。

### 层级3：10%小众特殊需求（完全定时离线批量，业务高峰关闭推理）
1. 人文安抚、情绪朗读：IndexTTS2；
2. 小众方言、少数民族、复刻患者本人声音：OmniVoice；
3. 自定义全新音色、超长多语种病历配音：VoxCPM-0.5B GGUF；
4. 精品高清病历音频素材制作：Qwen3-TTS 1.7B。

## 四、全系列CPU生产环境强制通用约束（避免数据库连接耗尽）
1. 所有TTS进程**单线程串行推理**，禁用多请求并行合成；
2. 强制限制Torch推理线程，预留4~8核CPU给Spring服务、MySQL：
```python
import os, torch
os.environ["CUDA_VISIBLE_DEVICES"] = "-1" # 屏蔽GPU强制CPU
torch.set_num_threads(8) # 仅分配部分物理核心给TTS
torch.set_num_interop_threads(2)
```
3. 长文本统一拆分≤150字分段合成，降低瞬时内存峰值；
4. 高内存/慢速模型（OmniVoice、VoxCPM、Qwen3-1.7B）仅定时任务执行，白天业务高峰期完全关闭推理；
5. 全部生成音频本地持久化缓存，前端优先读取缓存文件，大幅减少实时TTS调用次数。

---

# VoxCPM（VoxCPM2）完整介绍 + 纯CPU部署说明 + 四模型横向对比
## 一、基础信息（OpenBMB 开源TTS）
### 1. 开发主体 & 开源地址
联合研发：OpenBMB + 清华人机语音实验室 + ModelBest
- GitHub主仓库：https://github.com/OpenBMB/VoxCPM
- HuggingFace权重：https://huggingface.co/openbmb/VoxCPM2
- GGUF量化离线版本（CPU首选）：https://huggingface.co/bluryar/VoxCPM-GGUF
- PyPI一键安装：`pip install voxcpm`
- 开源协议：**Apache-2.0，免费商用**

### 2. 核心架构与版本
1. **VoxCPM2 主流版本：2B参数**，基于MiniCPM-4大语言主干，**Tokenizer-Free无音素分词**端到端扩散自回归架构
2. 轻量小参版：VoxCPM-0.5B，CPU压力更小
3. 采样率48kHz高保真，支持流式合成、文字生成音色、零样本语音克隆、30国语言+9种中文方言

### 3. 核心特色
- 无分词预处理：中文多音字、长句韵律天然更自然，无断句生硬问题
- Voice Design：纯文字描述生成全新音色（无需参考音频）
- 高相似度克隆：3~5秒人声即可复刻音色、情绪、口音
- 超长上下文支持：最大8192文本，适合完整病情长文本朗读

## 二、纯CPU环境运行完整结论
### 1. 能否CPU跑？
**完全支持Windows/Linux纯CPU离线推理**，无GPU也能运行，但原生FP32速度很慢；
推荐两种CPU加速方案：
1. GGUF量化（llama.cpp后端，Windows最优）Q4_K/Q8_0，内存减半、速度提升3~5倍
2. OpenVINO INT8导出，英特尔CPU专属加速

### 2. 硬件门槛（8核16线程 x86、128G内存环境）
| 版本 | 内存占用 | 10秒音频CPU耗时 |
|------|---------|----------------|
| VoxCPM2-2B FP32 | 10~12GB | 60~90秒 |
| VoxCPM-0.5B Q4_K GGUF | 3.6~4.2GB | 25~40秒 |
| VoxCPM-0.5B Q8_0 GGUF | 5~5.8GB | 18~30秒 |

### 3. CPU致命短板（适配你的医疗后台场景）
1. **推理速度极慢**，RTF普遍5~6，10秒音频CPU生成半分钟以上，**严禁实时高频播报**；
2. 2B大参版本内存占用超10GB，多服务共存极易抢占内存、CPU，加剧Druid数据库连接池耗尽；
3. 克隆模式推理耗时再翻倍，批量克隆只适合凌晨定时缓存音频；
4. 仅支持**单任务串行**，多并发直接CPU满载卡死业务接口。

### 4. CPU部署优化要点
```python
# 强制只用CPU
import os
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
import torch
torch.set_num_threads(8) # 绑定物理核心，预留CPU给Spring+MySQL
```
1. 优先选用 **0.5B GGUF量化包**，放弃2B大模型做在线播报；
2. 业务层使用内存队列串行，生成音频本地缓存，前端直接读缓存不实时推理；
3. 长文本拆分为≤150字分段合成，避免一次性加载超大上下文OOM；
4. Windows优先GGUF+llama.cpp，比原生PyTorch CPU快一倍。

## 三、四模型纯CPU横向总对比（OmniVoice / CosyVoice2-0.5B / PaddleSpeech / VoxCPM2-0.5B）
统一基准：8核16线程CPU、INT8/GGUF量化、单线程串行、医疗离线播报场景
| 对比维度 | VoxCPM-0.5B GGUF | OmniVoice(小米0.8B) | CosyVoice2-0.5B | PaddleSpeech FastSpeech2 |
| ---- | ---- | ---- | ---- | ---- |
| 模型参数量 | 0.5B | 0.8B | 0.5B | 0.1B级轻量 |
| 量化后内存占用 | 3.6~4.2GB | 2.8~3.5GB | 1.8~2.2GB | 600~900MB |
| CPU RTF(短句) | 3~6 | 5~10 | 2~4 | 0.8~1.5（实时级） |
| 流式合成 | ✅ 支持 | ❌ 不支持分段流式 | ✅ 原生低延迟流式 | ✅ PP-TTS流式 |
| 语音克隆能力 | ⭐⭐⭐⭐⭐ 文字造音+高相似度克隆 | ⭐⭐⭐⭐⭐ 多语种克隆 | ⭐⭐⭐⭐ 稳定克隆 | ❌ 无原生克隆 |
| 语种/方言 | 30语言+9中文方言 | 646种海量语种方言 | 中英日韩+少量方言 | 仅标准普通话、少量方言包 |
| 中文自然度 | ⭐⭐⭐⭐⭐ 无分词，韵律极强 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ 均衡流畅 | ⭐⭐⭐⭐ 清晰规整，机械感略高 |
| CPU并发容忍度 | 极差，仅串行低频 | 极差，不可并发 | 差，单队列串行 | 中等，短提示音轻度并发 |
| Windows部署难度 | 中（GGUF优化友好） | 高（Torch易OOM） | 中（国内ModelScope下载稳） | 极低，pip一键安装 |
| 核心短板（CPU） | 速度慢，大版本内存爆炸 | 扩散模型推理最慢、长文本OOM | CPU速度一般，克隆翻倍耗时 | 无音色克隆、语种单一 |
| 适合医疗场景 | 低频批量个性化朗读、自定义音色生成缓存 | 多方言/少数民族、患者音色复刻离线批量 | 长文本病情朗读、中等频次播报 | 高频设备提示音、实时交互播报（主力首选） |

## 四、医疗内网纯CPU落地选型建议（结合你128G Windows服务器+Druid连接池问题）
1. **日常高频设备提示、实时语音交互**：PaddleSpeech FastSpeech2
   内存占用最低、CPU消耗最小，不抢占数据库算力，稳定不拖垮业务。
2. **长文本病情朗读、追求极致中文自然流畅**：CosyVoice2-0.5B INT8
   平衡音质与CPU速度，单独队列避开业务高峰。
3. **需要复刻患者人声、小众方言播报**：OmniVoice（凌晨定时批量缓存音频）
4. **自定义全新音色、多语种病历朗读、高端音频内容制作**：VoxCPM-0.5B GGUF
   仅离线批量生成音频缓存，**禁止业务高峰期实时推理**，防止CPU满载导致数据库拿不到连接。

## 五、四款模型开源&权重地址汇总
1. VoxCPM
   代码：https://github.com/OpenBMB/VoxCPM
   权重：https://huggingface.co/openbmb/VoxCPM2
   GGUF量化CPU包：https://huggingface.co/bluryar/VoxCPM-GGUF
2. OmniVoice（小米）
   代码：https://github.com/k2-fsa/OmniVoice
   权重：https://huggingface.co/k2-fsa/OmniVoice
3. CosyVoice2-0.5B（阿里）
   代码：https://github.com/FunAudioLLM/CosyVoice
   国内权重：https://www.modelscope.cn/models/iic/CosyVoice2-0.5B
4. PaddleSpeech（百度）
   GitHub：https://github.com/PaddlePaddle/PaddleSpeech
   Gitee国内镜像：https://gitee.com/paddlepaddle/PaddleSpeech
   模型：pip安装后自动CDN下载，无需手动拉取



---






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

---

## 六、MiMo-V2.5-TTS 流式 Provider 集成（2026-07-01）

> [MiMo 开放平台文档（V2.5-TTS）](https://platform.xiaomimimo.com/docs/usage-guide/speech-synthesis-v2.5)

### 概述

新增 `core/providers/tts/mimo_tts_stream.py`，基于小米 MiMo-V2.5-TTS 模型的 OpenAI 兼容接口实现流式 TTS。使用 HTTP POST + SSE (Server-Sent Events) 协议，实时接收 PCM16 音频并转换为 Opus 推送到设备。

### API 协议

| 项 | 值 |
|------|------|
| 端点 | `POST https://api.xiaomimimo.com/v1/chat/completions` |
| 认证 | `api-key` 请求头 |
| 请求体 | `{"model":"mimo-v2.5-tts","messages":[{"role":"assistant","content":"文本"}],"audio":{"format":"pcm16","voice":"茉莉"},"stream":true}` |
| 响应 | SSE 格式：`data: {"choices":[{"index":0,"delta":{"audio":{"data":"base64_pcm"}}}]}` |
| 音频 | PCM16 24000Hz 单声道 16bit，base64 编码逐 chunk 传输 |
| 结束标记 | `data: [DONE]` |

### 实现细节

**文件**：`core/providers/tts/mimo_tts_stream.py`（218 行）

**模式**：`InterfaceType.SINGLE_STREAM`（覆盖 `tts_text_priority_thread`）

**核心流程**：

```
tts_text_priority_thread (覆盖基类)
  │
  ├─ SentenceType.FIRST
  │    └─ 重置 tts_stop_request, processed_chars, tts_text_buff
  │
  ├─ ContentType.TEXT
  │    └─ 累积到 tts_text_buff
  │         └─ _get_segment_text() 找到完整句子
  │              └─ to_tts_single_stream(segment_text)
  │                   └─ asyncio.run(text_to_speak(text))
  │                        └─ POST /v1/chat/completions (stream=True)
  │                             └─ resp.content.iter_any() 读取 SSE
  │                                  ├─ 逐行解析 data: {json}
  │                                  ├─ choices[0].delta.audio.data → base64解码
  │                                  └─ opus_encoder → handle_opus → 音频队列
  │
  ├─ ContentType.FILE
  │    └─ _process_audio_file_stream
  │
  └─ SentenceType.LAST
       └─ _process_remaining_text_stream
```

**SSE 数据流转换**：

```
SSE data: → JSON 解析 → delta.audio.data (base64)
  → base64.b64decode → PCM bytes (24000Hz, 16bit)
  → pcm_buffer 累积 → 帧切割 (2880 bytes/帧@60ms)
  → opus_encoder.encode_pcm_to_opus_stream
  → handle_opus → tts_audio_queue
```

### 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/providers/tts/mimo_tts_stream.py` | **新增** | 218 行，完整的 MiMo TTS SSE 流式 Provider |
| `config.yaml` | 修改 | TTS 段新增 `MiMoTTStream` 配置项 |

### 支持音色

| 性别 | 音色 |
|------|------|
| 中文女性 | 冰糖、茉莉 |
| 中文男性 | 苏打、白桦 |
| 英文女性 | Mia、Chloe |
| 英文男性 | Milo、Dean |
| 默认 | MiMo-默认 |

风格标签：开心、悲伤、愤怒、恐惧、惊讶、兴奋、平静、温柔、活泼、俏皮、磁性、清亮、甜美、台湾腔、粤语、四川话、东北话、唱歌 等 40+ 种。

### 自测结果

| # | 测试项 | 结果 |
|---|--------|------|
| 1 | 模块导入与 SSL 兼容 | ✅ |
| 2 | 全部 6 个关键方法存在且可调用 | ✅ |
| 3 | 构造函数参数（api_key, voice, model, interface_type） | ✅ |
| 4 | private_voice 私有音色覆盖 | ✅ |
| 5 | `text_to_speak` 关键逻辑：POST、api-key、SSE、base64→Opus | ✅ 13 项 |
| 6 | 请求体结构（model、messages、audio、stream） | ✅ |
| 7 | `to_tts` 非流式路径 | ✅ |
| 8 | `to_tts_single_stream` 重试逻辑（5 次） | ✅ |
| 9 | SSE 数据包模拟解析（base64 PCM 2880 字节帧） | ✅ |
| 10 | 空文本缓冲区不崩溃 | ✅ |
| 11 | FIRST/LAST 队列生命周期完整 | ✅ |
| — | pytest 全量 81 个测试 | ✅ |
| — | `python app.py` 启动 | ✅ 零错误 |

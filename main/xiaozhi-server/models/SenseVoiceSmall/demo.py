from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess
import os

# ========== 核心配置（根据你的实际情况修改） ==========
# 方案1：加载本地模型（需确保 ./ 下有完整模型文件）
model_dir = "./"  # 若本地无模型，改用方案2加载官方预训练模型
# 方案2：加载官方预训练的 SenseVoiceSmall 模型（推荐新手）
# model_dir = "iic/SenseVoiceSmall"

# 替换为你自己的音频文件路径（支持wav/mp3，建议16kHz单声道）
audio_path = "./example/1.mp3"  # 可替换为你的英文音频文件，如 "test.wav"

# ========== 模型加载（修复参数问题） ==========
model = AutoModel(
    model=model_dir,
    vad_model="fsmn-vad",
    vad_kwargs={"max_single_segment_time": 30000},
    device="cpu",  # auto:自动选择cpu/gpu，如果auto不支持，需要将 device="auto" 改为具体的设备类型（优先选 cpu(cpu必须小写！大写 CPU 会报错)，新手无需纠结 GPU）
    disable_update=True,  # 关闭版本检查提示，可选
)

# ========== 检查音频文件是否存在 ==========
if not os.path.exists(audio_path):
    print(f"❌ 错误：音频文件 {audio_path} 不存在！")
    print("请将 audio_path 替换为你本地的音频文件路径（如 'test.mp3'）")
else:
    # ========== 语音识别推理（修复参数错误） ==========
    res = model.generate(
        input=audio_path,
        cache={},  # 1.3.0 版本要求字典类型,（空字典，用于存储流式识别的中间缓存数据）
        language="zh",  # 识别英文，正确值：zh(中)/en(英)/yue(粤)/ja(日)/ko(韩)
        use_itn=True,
        batch_size_s=60,
        merge_vad=True,
        merge_length_s=15,
    )

    # ========== 结果后处理与输出 ==========
    text = rich_transcription_postprocess(res[0]["text"])
    print("📌 识别结果：")
    print(f"原始文本：{res[0]['text']}")
    print(f"后处理文本：{text}")
from funasr import AutoModel
import soundfile as sf
import librosa
import time  # 用于计时

# ------------------- 计时开始：总耗时 -------------------
total_start = time.time()

# ------------------- 加载模型 + 计时 -------------------
print("正在加载模型...")
model_start = time.time()

model = AutoModel(model="../../models/SenseVoiceSmall")

model_time = time.time() - model_start
print(f"✅ 模型加载完成，耗时：{model_time:.2f} 秒\n")

# ------------------- 音频识别 + 计时 -------------------
audio_path = "../../models/SenseVoiceSmall/example/1.mp3"

print("正在识别音频...")
rec_start = time.time()

# 读取音频（必须 16k 采样率）
data, sr = librosa.load(audio_path, sr=16000)

# 推理
res = model.generate(
    input=data,
    language="auto",
    use_itn=True
)

# 识别耗时
rec_time = time.time() - rec_start

# ------------------- 输出结果 -------------------
print("="*50)
print("识别结果：", res[0]["text"])
print("="*50)

# ------------------- 耗时统计输出 -------------------
print(f"\n⏱  模型加载耗时：{model_time:.2f} s")
print(f"⏱  音频识别耗时：{rec_time:.2f} s")
print(f"⏱  总运行耗时：{time.time() - total_start:.2f} s")
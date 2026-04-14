# -*- coding: utf-8 音量增大版本, 存在颤音 -*-
import edge_tts
import os
import time
import asyncio
from pydub import AudioSegment

TEXT = "君不见，黄河之水天上来，奔流到海不复回。君不见，高堂明镜悲白发，朝如青丝暮成雪。人生得意须尽欢，莫使金樽空对月。"
VOICE = "zh-CN-XiaoxiaoNeural"
OUTPUT_DIR = "test_edge_tts_async_output"


async def test_edge_tts_async():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    filename = f"test_async_{int(time.time())}.mp3"
    output_path = os.path.join(OUTPUT_DIR, filename)

    # 临时文件
    temp_file = "temp_audio.mp3"

    start_time = time.perf_counter()

    # 1. 先生成原版音频（官方方式，无颤音）
    tts = edge_tts.Communicate(
        text=TEXT,
        voice=VOICE,
        rate="+0%",
        volume="+0%",
        pitch="+0Hz"
    )
    await tts.save(temp_file)

    # 2. 放大音量（真正有效，放大 25dB）
    audio = AudioSegment.from_file(temp_file, format="mp3")
    audio = audio + 25  # 音量超级大（最大安全值）
    audio.export(output_path, format="mp3")

    # 删除临时文件
    if os.path.exists(temp_file):
        os.remove(temp_file)

    # 耗时统计
    cost_time = time.perf_counter() - start_time

    print(f"✅ 合成完成：{output_path}")
    print(f"⏱  总耗时：{cost_time:.3f} 秒")
    print(f"📝 文本长度：{len(TEXT)} 字符")
    print(f"🔊 音量已放大 25dB（超大音量）")


if __name__ == "__main__":
    asyncio.run(test_edge_tts_async())
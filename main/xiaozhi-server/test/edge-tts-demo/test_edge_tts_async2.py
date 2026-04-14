# -*- coding: utf-8   音量正常版本-*-
import edge_tts
import os
import time
import asyncio

TEXT = "君不见，黄河之水天上来，奔流到海不复回。君不见，高堂明镜悲白发，朝如青丝暮成雪。人生得意须尽欢，莫使金樽空对月。"
VOICE = "zh-CN-XiaoxiaoNeural"
OUTPUT_DIR = "test_edge_tts_async_output"

async def test_edge_tts_async():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    filename = f"test_async_{int(time.time())}.mp3"
    output_path = os.path.join(OUTPUT_DIR, filename)

    tts = edge_tts.Communicate(
        text=TEXT,
        voice=VOICE,
        rate="+0%",
        volume="+100%",  # 音量增大
        pitch="+0Hz"
    )

    # ===================== 耗时统计 =====================
    start_time = time.perf_counter()

    await tts.save(output_path)

    end_time = time.perf_counter()
    cost_time = end_time - start_time
    # =====================================================

    print(f"✅ 异步合成完成：{output_path}")
    print(f"⏱  总耗时：{cost_time:.3f} 秒")
    print(f"📝 文本长度：{len(TEXT)} 字符")

if __name__ == "__main__":
    asyncio.run(test_edge_tts_async())
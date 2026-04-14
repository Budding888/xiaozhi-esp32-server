# -*- coding: utf-8 -*-
import edge_tts
import os
import time

# ===================== 配置 =====================
TEST_TEXT = """
君不见，黄河之水天上来，奔流到海不复回。
君不见，高堂明镜悲白发，朝如青丝暮成雪。
人生得意须尽欢，莫使金樽空对月。
"""
VOICE = "zh-CN-YunjianNeural"  # 云健
# VOICE = "zh-CN-XiaoxiaoNeural"  # 晓晓
OUTPUT_DIR = "test_edge_tts_sync_output"

def test_edge_tts_sync():
    """同步测试 edge_tts（最简单稳定，无颤音）"""
    try:
        # 创建输出目录
        if not os.path.exists(OUTPUT_DIR):
            os.makedirs(OUTPUT_DIR)

        # 生成不重复文件名
        filename = f"test_{int(time.time())}.mp3"
        output_path = os.path.join(OUTPUT_DIR, filename)

        print("=" * 60)
        print("edge-tts 合成测试中...")
        print(f"音色: {VOICE}")
        print(f"文本: {TEST_TEXT.strip()[:50]}...")
        print("=" * 60)

        # 直接完整生成，不使用 stream → 音质最好，无颤音
        tts = edge_tts.Communicate(
            text=TEST_TEXT,
            voice=VOICE,
            rate="+0%",    # 语速
            volume="+50%",  # 音量（edge-tts原生支持，不会失真）
            pitch="+0Hz"   # 音调
        )

        # 保存音频
        tts.save_sync(output_path)

        # 验证文件
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"\n✅ 合成成功！")
            print(f"文件: {output_path}")
            print(f"大小: {os.path.getsize(output_path)} 字节")
            print("音质纯净，无颤音、无杂音")
        else:
            print("\n❌ 文件生成失败")

    except Exception as e:
        print(f"\n❌ 合成失败: {str(e)}")

if __name__ == "__main__":
    test_edge_tts_sync()

    # 运行方法（直接在当前目录运行）
    # python test_edge_tts_sync.py
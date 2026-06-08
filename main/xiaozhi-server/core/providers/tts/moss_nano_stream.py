import io
import wave
import json
import base64
import asyncio
import websockets
from config.logger import setup_logging
from core.providers.tts.base import TTSProviderBase
from core.providers.tts.dto.dto import InterfaceType

TAG = __name__
logger = setup_logging()


class TTSProvider(TTSProviderBase):
    TTS_PARAM_CONFIG = [
        ("ttsVolume", "volume", 0, 3, 1.0, lambda v: round(float(v), 1)),
        ("ttsRate", "speed", 0, 3, 1.0, lambda v: round(float(v), 1)),
    ]

    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        self.interface_type = InterfaceType.NON_STREAM
        print(f"---------paddlespeech------config----------：{config}")
        self.url = config.get("url", "ws://127.0.0.1:8119/v1/tts/streaming")
        # 获取配置的音色编码: 优先获取 智能体-角色配置中配置的【private_voice】音色编码，如果没有则使用全局配置的音色编码
        self.spk_id = config.get("private_voice") or config.get("spk_id", "zh_putong_man")

        speed = config.get("speed")
        self.speed = float(speed) if speed else 1.0
        volume = config.get("volume")
        self.volume = float(volume) if volume else 1.0

        self._apply_percentage_params(config)

    @staticmethod
    async def pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000, num_channels: int = 1, bits_per_sample: int = 16) -> bytes:
        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wav_file:
            wav_file.setnchannels(num_channels)
            wav_file.setsampwidth(bits_per_sample // 8)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        return wav_io.getvalue()

    async def text_to_speak(self, text, output_file):
        return await self._text_streaming(text, output_file)

    @staticmethod
    def _normalize_pcm(pcm_data: bytes) -> bytes:
        """对 PCM16 数据进行峰值归一化，提升音量清晰度"""
        import struct

        samples = list(struct.iter_unpack("<h", pcm_data))
        if not samples:
            return pcm_data
        values = [s[0] for s in samples]
        max_val = max(abs(v) for v in values)
        if max_val < 16384:
            gain = 24576.0 / (max_val if max_val > 0 else 1)
            new_values = [max(-32768, min(32767, int(v * gain))) for v in values]
            return struct.pack(f"<{len(new_values)}h", *new_values)
        return pcm_data

    async def _text_streaming(self, text, output_file):
        try:
            async with websockets.connect(self.url) as ws:
                await ws.send(json.dumps({"task": "tts", "signal": "start", "spk_id": self.spk_id}))

                start_response = json.loads(await ws.recv())
                if start_response.get("status") != 0:
                    raise RuntimeError(f"Moss-Nano TTS 连接失败: {start_response.get('message', 'unknown')}")

                session_id = start_response["session"]
                await ws.send(json.dumps({"text": text, "spk_id": self.spk_id}))

                audio_chunks = b""
                sample_rate = 24000
                channels = 1
                timeout = 60
                try:
                    while True:
                        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
                        status = response.get("status")
                        if status == 2:
                            break
                        audio_chunks += base64.b64decode(response["audio"])
                        if "sample_rate" in response:
                            sample_rate = int(response["sample_rate"])
                        if "channels" in response:
                            channels = int(response["channels"])
                except asyncio.TimeoutError:
                    raise TimeoutError(f"Moss-Nano TTS 等待音频数据超时 ({timeout}s)")

                audio_chunks = self._normalize_pcm(audio_chunks)
                wav_data = await self.pcm_to_wav(audio_chunks, sample_rate, channels)

                await ws.send(json.dumps({"task": "tts", "signal": "end", "session": session_id}))
                await ws.recv()

                if output_file:
                    with open(output_file, "wb") as f:
                        f.write(wav_data)
                else:
                    return wav_data

        except Exception as e:
            raise RuntimeError(f"Moss-Nano TTS 请求失败: {e}") from e
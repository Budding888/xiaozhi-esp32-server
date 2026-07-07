"""
MiMo-V2.5-TTS 流式 TTS Provider

基于 Xiaomi MiMo-V2.5-TTS 模型的 OpenAI 兼容接口。
通过 HTTP POST + SSE (Server-Sent Events) 流式接收 PCM16 音频数据。

API: POST https://api.xiaomimimo.com/v1/chat/completions
Auth: api-key header
Format: PCM16 24000Hz 单声道 16bit (base64 编码在 SSE 中传输)
"""
import os
import json
import base64
import time
import queue

# SSL 兼容性补丁（在 aiohttp 导入前执行）
import ssl as _ssl
try:
    _ssl.create_default_context()
except _ssl.SSLError:
    import certifi as _certifi
    _original_create_default_context = _ssl.create_default_context
    def _patched_create_default_context(*args, **kwargs):
        try:
            return _original_create_default_context(*args, **kwargs)
        except _ssl.SSLError:
            _ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
            _ctx.load_verify_locations(_certifi.where())
            return _ctx
    _ssl.create_default_context = _patched_create_default_context

import aiohttp
import asyncio
import requests
import traceback
from config.logger import setup_logging
from core.utils.tts import MarkdownCleaner
from core.providers.tts.base import TTSProviderBase
from core.utils import opus_encoder_utils, textUtils
from core.providers.tts.dto.dto import SentenceType, ContentType, InterfaceType

TAG = __name__
logger = setup_logging()


class TTSProvider(TTSProviderBase):
    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        self.interface_type = InterfaceType.SINGLE_STREAM
        self.api_key = config.get("api_key", "")
        self.api_url = config.get(
            "api_url", "https://api.xiaomimimo.com/v1/chat/completions"
        )
        self.voice = config.get("voice", "茉莉")
        if config.get("private_voice"):
            self.voice = config.get("private_voice")
        self.audio_format = "pcm16"
        self.model = config.get("model", "mimo-v2.5-tts")
        self.before_stop_play_files = []

        # 创建 Opus 编码器（MiMo 输出为 24000Hz PCM16）
        self.opus_encoder = opus_encoder_utils.OpusEncoderUtils(
            sample_rate=24000, channels=1, frame_size_ms=60
        )
        # PCM 缓冲区（用于拼帧）
        self.pcm_buffer = bytearray()

    def tts_text_priority_thread(self):
        """流式文本处理线程"""
        while not self.conn.stop_event.is_set():
            try:
                message = self.tts_text_queue.get(timeout=1)
                if message.sentence_type == SentenceType.FIRST:
                    # 初始化参数
                    self.tts_stop_request = False
                    self.processed_chars = 0
                    self.tts_text_buff = []
                    self.before_stop_play_files.clear()

                elif ContentType.TEXT == message.content_type:
                    self.tts_text_buff.append(message.content_detail)
                    segment_text = self._get_segment_text()
                    if segment_text:
                        self.to_tts_single_stream(segment_text)

                elif ContentType.FILE == message.content_type:
                    logger.bind(tag=TAG).info(
                        f"添加音频文件到待播放列表: {message.content_file}"
                    )
                    if message.content_file and os.path.exists(message.content_file):
                        self._process_audio_file_stream(
                            message.content_file,
                            callback=lambda audio_data: self.handle_audio_file(
                                audio_data, message.content_detail
                            ),
                        )

                if message.sentence_type == SentenceType.LAST:
                    # 处理剩余的文本
                    self._process_remaining_text_stream(True)

            except queue.Empty:
                continue
            except Exception as e:
                logger.bind(tag=TAG).error(
                    f"处理TTS文本失败: {str(e)}, 类型: {type(e).__name__}, 堆栈: {traceback.format_exc()}"
                )
                continue

    def _process_remaining_text_stream(self, is_last=False):
        """处理剩余的文本并生成语音"""
        full_text = "".join(self.tts_text_buff)
        remaining_text = full_text[self.processed_chars :]
        if remaining_text:
            segment_text = textUtils.get_string_no_punctuation_or_emoji(remaining_text)
            if segment_text:
                self.to_tts_single_stream(segment_text, is_last)
                self.processed_chars += len(full_text)
            else:
                self._process_before_stop_play_files()
        else:
            self._process_before_stop_play_files()

    def to_tts_single_stream(self, text, is_last=False):
        """发送单句文本到 MiMo TTS 并在流式响应中处理音频"""
        try:
            max_repeat_time = 5
            text = MarkdownCleaner.clean_markdown(text)
            while max_repeat_time > 0:
                try:
                    asyncio.run(self.text_to_speak(text, is_last))
                    logger.bind(tag=TAG).info(
                        f"MiMo TTS成功: {text[:30]}... 重试{5 - max_repeat_time}次"
                    )
                    break
                except Exception as e:
                    logger.bind(tag=TAG).warning(
                        f"MiMo TTS失败{5 - max_repeat_time + 1}次: {text[:30]}..., 错误: {e}"
                    )
                    max_repeat_time -= 1
            if max_repeat_time <= 0:
                logger.bind(tag=TAG).error(f"MiMo TTS重试耗尽: {text[:30]}...")
        except Exception as e:
            logger.bind(tag=TAG).error(f"MiMo TTS异常: {e}")
        finally:
            return None

    async def text_to_speak(self, text, is_last):
        """
        向 MiMo API 发送 POST 请求，通过 SSE 流式接收 PCM16 音频数据

        SSE 响应格式：
            data: {"choices":[{"index":0,"delta":{"audio":{"data":"base64_pcm"}}}]}
            data: [DONE]
        """
        # 一帧 PCM 字节数: 60ms × 24000Hz × 1ch × 2bytes = 2880
        frame_bytes = int(
            self.opus_encoder.sample_rate
            * self.opus_encoder.channels
            * self.opus_encoder.frame_size_ms
            / 1000
            * 2
        )

        # 构建请求体
        messages = [{"role": "assistant", "content": text}]
        payload = {
            "model": self.model,
            "messages": messages,
            "audio": {
                "format": self.audio_format,
                "voice": self.voice,
            },
            "stream": True,
        }
        headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url, json=payload, headers=headers, timeout=60
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.bind(tag=TAG).error(
                            f"MiMo API请求失败: HTTP {resp.status}, {error_text[:200]}"
                        )
                        self.tts_audio_queue.put((SentenceType.LAST, [], None))
                        return

                    self.pcm_buffer.clear()
                    self.tts_audio_queue.put((SentenceType.FIRST, [], text))

                    # 读取 SSE 流
                    sse_buffer = ""
                    async for chunk in resp.content.iter_any():
                        if not chunk:
                            continue
                        sse_buffer += chunk.decode("utf-8", errors="replace")

                        # 按行处理 SSE 数据
                        while "\n" in sse_buffer:
                            line, sse_buffer = sse_buffer.split("\n", 1)
                            line = line.strip()
                            if not line:
                                continue

                            # SSE data: 开头（兼容中英文冒号）
                            data_str = None
                            if line.startswith("data:"):
                                data_str = line[5:].strip()
                            elif line.startswith("data："):
                                data_str = line[5:].strip()
                            else:
                                continue

                            if data_str == "[DONE]":
                                continue

                            # 解析 SSE 中的音频数据
                            try:
                                sse_data = json.loads(data_str)
                                choices = sse_data.get("choices", [])
                                if not choices:
                                    continue
                                delta = choices[0].get("delta", {})
                                audio_data = (
                                    delta.get("audio", {}).get("data")
                                )
                                if not audio_data:
                                    continue

                                # base64 → PCM bytes
                                pcm_bytes = base64.b64decode(audio_data)
                                if not pcm_bytes:
                                    continue

                                self.pcm_buffer.extend(pcm_bytes)

                                # 按帧编码为 Opus
                                while len(self.pcm_buffer) >= frame_bytes:
                                    frame = bytes(self.pcm_buffer[:frame_bytes])
                                    del self.pcm_buffer[:frame_bytes]
                                    self.opus_encoder.encode_pcm_to_opus_stream(
                                        frame,
                                        end_of_stream=False,
                                        callback=self.handle_opus,
                                    )
                            except json.JSONDecodeError:
                                continue
                            except Exception as e:
                                logger.bind(tag=TAG).debug(
                                    f"SSE 数据解析异常: {e}"
                                )
                                continue

                    # flush 剩余 PCM 数据
                    if self.pcm_buffer:
                        self.opus_encoder.encode_pcm_to_opus_stream(
                            bytes(self.pcm_buffer),
                            end_of_stream=True,
                            callback=self.handle_opus,
                        )
                        self.pcm_buffer.clear()

                    if is_last:
                        self._process_before_stop_play_files()

        except asyncio.TimeoutError:
            logger.bind(tag=TAG).error("MiMo API 请求超时")
            self.tts_audio_queue.put((SentenceType.LAST, [], None))
        except Exception as e:
            logger.bind(tag=TAG).error(
                f"MiMo API 请求异常: {type(e).__name__}: {e}"
            )
            self.tts_audio_queue.put((SentenceType.LAST, [], None))

    async def close(self):
        """资源清理"""
        await super().close()
        if hasattr(self, "opus_encoder"):
            self.opus_encoder.close()

    def to_tts(self, text: str) -> list:
        """非流式 TTS 处理（一次性返回完整音频）"""
        start_time = time.time()
        text = MarkdownCleaner.clean_markdown(text)

        payload = {
            "model": self.model,
            "messages": [{"role": "assistant", "content": text}],
            "audio": {"format": "wav", "voice": self.voice},
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key,
        }

        try:
            with requests.post(
                self.api_url, json=payload, headers=headers, timeout=30
            ) as response:
                if response.status_code != 200:
                    logger.bind(tag=TAG).error(
                        f"MiMo TTS请求失败: {response.status_code}, {response.text[:200]}"
                    )
                    return []

                data = response.json()
                audio_data = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("audio", {})
                    .get("data")
                )
                if not audio_data:
                    logger.bind(tag=TAG).error("MiMo 响应中未找到音频数据")
                    return []

                pcm_bytes = base64.b64decode(audio_data)
                frame_bytes = int(
                    self.opus_encoder.sample_rate
                    * self.opus_encoder.channels
                    * self.opus_encoder.frame_size_ms
                    / 1000
                    * 2
                )
                opus_datas = []
                for i in range(0, len(pcm_bytes), frame_bytes):
                    frame = pcm_bytes[i : i + frame_bytes]
                    if len(frame) < frame_bytes:
                        frame += b"\x00" * (frame_bytes - len(frame))
                    self.opus_encoder.encode_pcm_to_opus_stream(
                        frame,
                        end_of_stream=(i + frame_bytes >= len(pcm_bytes)),
                        callback=lambda opus: opus_datas.append(opus),
                    )
                logger.bind(tag=TAG).info(
                    f"MiMo TTS非流式完成: {text[:30]}..., 耗时: {time.time() - start_time:.2f}s"
                )
                return opus_datas

        except Exception as e:
            logger.bind(tag=TAG).error(f"MiMo TTS非流式异常: {e}")
            return []

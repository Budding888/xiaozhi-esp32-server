import os
import uuid
import json
import queue
import asyncio
import threading
import traceback

from typing import Callable, Any
from config.logger import setup_logging
from core.utils.util import check_model_key
from core.utils.tts import MarkdownCleaner, convert_percentage_to_range
from core.providers.tts.base import TTSProviderBase
from core.providers.tts.dto.dto import SentenceType, ContentType, InterfaceType
from core.utils import opus_encoder_utils

try:
    import dashscope
    from dashscope.audio.tts_v2 import SpeechSynthesizer, ResultCallback, AudioFormat
    _DASHSCOPE_AVAILABLE = True
except Exception:  # pragma: no cover - SDK 缺失时的兜底
    dashscope = None
    SpeechSynthesizer = None
    ResultCallback = object
    AudioFormat = None
    _DASHSCOPE_AVAILABLE = False


TAG = __name__
logger = setup_logging()

# 结束会话时等待 SDK on_complete 回调的上限（秒）。
# 超时不会丢音频，只是不再等待，随后由兜底逻辑下发 LAST。
TTS_COMPLETE_WAIT_TIMEOUT = 30

# 服务端事件：一句话开始/结束合成，payload.output.original_text 为该句原文。
# 在该事件到达时把字幕推入播放队列，即可让文字与语音精确同步。
SENTENCE_BEGIN_EVENT = "sentence-begin"
SENTENCE_END_EVENT = "sentence-end"


class TTSProvider(TTSProviderBase):
    TTS_PARAM_CONFIG = [
        # (config_key, attr, min_val, max_val, base_val, transform)
        ("ttsVolume", "volume", 0, 100, 50, int),
        ("ttsRate", "speech_rate", 0.5, 2.0, 1.0, lambda v: round(v, 1)),
        ("ttsPitch", "pitch_rate", 0.5, 2.0, 1.0, lambda v: round(v, 1)),
    ]

    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)

        self.interface_type = InterfaceType.DUAL_STREAM

        # ---- 基础配置 ----
        self.api_key = config.get("api_key")
        if not self.api_key:
            raise ValueError("api_key is required for QwenAudio TTS")
        model_key_msg = check_model_key("TTS", self.api_key)
        if model_key_msg:
            logger.bind(tag=TAG).error(model_key_msg)

        self.model = config.get("model", "qwen-audio-3.0-tts-flash")
        # DashScope SDK 通过模块级全局变量读取 api_key / 端点，必须显式设置，
        # 否则会依赖其它 provider（如 ASR）恰好设置过，且顺序不确定。
        dashscope.api_key = self.api_key
        # WebSocket 端点：不同地域（北京/新加坡）配置不同，可在此覆盖 SDK 默认值
        self.base_websocket_api_url = config.get("base_websocket_api_url", "wss://ws-lahnz1fxxpirg9zl.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference")
        dashscope.base_websocket_api_url = self.base_websocket_api_url

        # 业务空间 ID（可选）
        self.workspace = config.get("workspace")

        # 音色
        if config.get("private_voice"):
            self.voice = config.get("private_voice")
        else:
            self.voice = config.get("voice", "longanhuan_v3.6")

        # 音频输出格式（SDK 侧输出，供编码前的原始数据）
        self.format = config.get("format", "pcm")

        # 音频参数
        volume = config.get("volume", "50")
        self.volume = int(volume) if volume else 50

        speech_rate = config.get("speech_rate", "1.0")
        self.speech_rate = float(speech_rate) if speech_rate else 1.0

        pitch_rate = config.get("pitch_rate", "1.0")
        self.pitch_rate = float(pitch_rate) if pitch_rate else 1.0

        # 应用百分比调整（如果存在），否则使用公有化配置
        self._apply_percentage_params(config)

        # 内容审查开关（可选）
        self._data_inspection_enabled = bool(config.get("data_inspection_enabled", True))

        # ---- 运行时状态 ----
        # DashScope SDK 内部使用自有的线程 + websocket-client，
        # 通过回调 on_data 在 SDK 线程上产出 PCM 字节。
        # 这里为 TTS 音频单独创建一个 Opus 编码器，避免与父类
        # audio_play_priority_thread 共享的 self.opus_encoder 并发冲突。
        self.tts_opus_encoder = None
        self.synthesizer = None
        # 用于把所有阻塞的 SDK 操作（connect/close/complete/cancel）
        # 放到单一工作线程，避免在事件循环上执行阻塞 I/O。
        self._sdk_worker: asyncio.Future | None = None
        self._encoder_lock = threading.Lock()
        # SDK on_complete 回调到达信号：finish_session 必须等到它，
        # 否则会过早关闭 WebSocket，丢掉尾部音频与 LAST 标记。
        self._complete_event = threading.Event()
        # 保证会话收尾（下发 LAST）只执行一次
        self._session_finalized = False

    async def open_audio_channels(self, conn):
        try:
            await super().open_audio_channels(conn)
            # 根据 conn 的实际采样率创建 TTS 专用 Opus 编码器
            self.tts_opus_encoder = opus_encoder_utils.OpusEncoderUtils(
                sample_rate=conn.sample_rate,
                channels=1,
                frame_size_ms=60,
            )
        except Exception as e:
            logger.bind(tag=TAG).error(f"Failed to open audio channels: {str(e)}")
            raise

    # ------------------------------------------------------------------
    # 会话生命周期
    # ------------------------------------------------------------------
    def _build_headers(self) -> dict:
        """构建请求头：可选地开启内容审查。"""
        headers = {}
        if config_get_data_inspection_enabled := self._data_inspection_enabled:
            headers["X-DashScope-DataInspection"] = "enable"
        return headers

    def _build_audio_format(self, sample_rate: int) -> "AudioFormat":
        """根据目标采样率映射到 SDK 的 AudioFormat 枚举。"""
        fmt = (self.format or "pcm").lower()
        try:
            sr = int(sample_rate)
        except (TypeError, ValueError):
            sr = 16000
        sr = max(8000, sr)
        if fmt == "pcm":
            mapping = {
                8000: "PCM_8000HZ_MONO_16BIT",
                16000: "PCM_16000HZ_MONO_16BIT",
                22050: "PCM_22050HZ_MONO_16BIT",
                24000: "PCM_24000HZ_MONO_16BIT",
                44100: "PCM_44100HZ_MONO_16BIT",
                48000: "PCM_48000HZ_MONO_16BIT",
            }
        else:
            mapping = {}
        name = mapping.get(sr)
        if name and hasattr(AudioFormat, name):
            return getattr(AudioFormat, name)
        return AudioFormat.DEFAULT

    async def start_session(self, session_id):
        logger.bind(tag=TAG).debug(f"开始会话～～{session_id}")
        try:
            # 清理上一个未结束的 synthesizer（阻塞操作放到工作线程）
            if self.synthesizer is not None:
                await self._close_synthesizer()

            sample_rate = getattr(self.conn, "sample_rate", 16000)
            audio_format = self._build_audio_format(sample_rate)

            # 新会话：复位完成信号与收尾标记
            self._complete_event.clear()
            self._session_finalized = False

            # 为本次会话绑定回调
            callback = _QwenAudioCallback(
                tag=TAG,
                on_audio=self._on_tts_audio,
                on_complete=self._on_tts_complete,
                on_error=self._on_tts_error,
                on_sentence=self._on_sentence_begin,
            )

            self.synthesizer = SpeechSynthesizer(
                model=self.model,
                voice=self.voice,
                format=audio_format,
                volume=self.volume,
                speech_rate=self.speech_rate,
                pitch_rate=self.pitch_rate,
                headers=self._build_headers(),
                callback=callback,
                workspace=self.workspace,
            )
            logger.bind(tag=TAG).debug(
                f"TTS 合成器已创建: model={self.model}, voice={self.voice}, "
                f"format={self.format}, sample_rate={sample_rate}"
            )
        except Exception as e:
            logger.bind(tag=TAG).error(f"启动会话失败: {str(e)}")
            await self._close_synthesizer()
            raise

    async def finish_session(self, session_id):
        logger.bind(tag=TAG).debug(f"关闭会话～～{session_id}")
        try:
            if self.synthesizer is not None:
                loop = asyncio.get_running_loop()
                # async_streaming_complete 只发送结束请求并立即返回（真正的收尾
                # 由 SDK 内部线程负责），必须等待 on_complete 回调再关闭 WebSocket，
                # 否则尾部音频和 LAST 标记都会丢失，客户端「说完」事件永远收不到。
                await loop.run_in_executor(
                    None,
                    lambda: self._safe_sdk_call(
                        self.synthesizer, "async_streaming_complete"
                    ),
                )
                completed = await loop.run_in_executor(
                    None, self._wait_tts_complete
                )
                if not completed:
                    logger.bind(tag=TAG).warning(
                        f"等待TTS合成完成超过 {TTS_COMPLETE_WAIT_TIMEOUT}s，直接收尾"
                    )
            # 兜底：on_complete 未触发（或已触发但被去重）时仍需保证 LAST 下发
            await self._finalize_session()
            await self._close_synthesizer()
        except Exception as e:
            logger.bind(tag=TAG).error(f"关闭会话失败: {str(e)}")
            await self._finalize_session()
            await self._close_synthesizer()
            raise

    def _wait_tts_complete(self) -> bool:
        """在工作线程内等待 SDK 的 on_complete 回调，返回是否等到。"""
        return self._complete_event.wait(timeout=TTS_COMPLETE_WAIT_TIMEOUT)

    async def cancel_session(self, session_id):
        logger.bind(tag=TAG).debug(f"取消会话～～{session_id}")
        try:
            if self.synthesizer is not None:
                # streaming_cancel 是阻塞操作（关闭 ws），放到工作线程
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: self._safe_sdk_call(self.synthesizer, "streaming_cancel"),
                )
            await self._close_synthesizer()
            # 取消路径不经过 on_complete，必须在这里发 LAST 标记终止播放线程
            if not self._session_finalized:
                self._session_finalized = True
                self.tts_audio_queue.put((SentenceType.LAST, [], None, session_id))
        except Exception as e:
            logger.bind(tag=TAG).error(f"取消会话失败: {str(e)}")
            await self._close_synthesizer()
            if not self._session_finalized:
                self._session_finalized = True
                self.tts_audio_queue.put((SentenceType.LAST, [], None, session_id))
            raise

    @staticmethod
    def _safe_sdk_call(synthesizer, method_name: str):
        """按名称调用 SDK 方法并吞掉预期内的异常（InvalidTask 等）。"""
        method = getattr(synthesizer, method_name, None)
        if method is None:
            return
        try:
            method()
        except Exception:
            pass

    async def _close_synthesizer(self, finish: bool = True):
        syn = self.synthesizer
        self.synthesizer = None
        if syn is not None:
            # 必须先下发 finish-task（async_streaming_complete）再关闭 ws：
            # 只做裸 ws.close() 不会通知服务端结束任务，服务端会话会残留，
            # 23 秒后被 SDK/服务端以 task-failed("request timeout after 23 seconds")
            # 形式报错（见线上日志 11:40:34 重建 → 11:40:58 失败）。
            # async_streaming_complete 只发结束请求并立即返回，真正的收尾
            # 由 SDK 内部线程负责；若任务尚未开始/已停止，_safe_sdk_call 会吞掉
            # 预期的 InvalidTask 异常。
            if finish:
                try:
                    await asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda: self._safe_sdk_call(
                            syn, "async_streaming_complete"
                        ),
                    )
                except Exception:
                    pass
            # ws.close() 是阻塞调用，放到工作线程执行
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: syn.close()
                )
            except Exception:
                pass

    async def close(self):
        await self._close_synthesizer()
        with self._encoder_lock:
            if self.tts_opus_encoder is not None:
                try:
                    self.tts_opus_encoder.close()
                except Exception:
                    pass
                self.tts_opus_encoder = None

    # ------------------------------------------------------------------
    # SDK 回调桥接（运行在 DashScope 内部线程）
    # ------------------------------------------------------------------
    def _on_tts_audio(self, pcm_data: bytes):
        """on_data 回调：把 PCM 字节编码为 Opus 帧并推入播放队列。"""
        if self.tts_opus_encoder is None:
            return
        try:
            self.tts_opus_encoder.encode_pcm_to_opus_stream(
                pcm_data,
                False,
                callback=self.handle_opus,
            )
        except Exception as e:
            logger.bind(tag=TAG).error(f"TTS 音频编码失败: {str(e)}")

    def _on_sentence_begin(self, text: str):
        """服务端开始合成一句话：把该句文字作为字幕推入播放队列。

        与音频帧共用 tts_audio_queue 的 FIRST 通道，且本事件先于该句的音频帧
        到达（同一个 SDK 线程、同一条 WebSocket），因此这句文字会被排在它自己
        的音频之前，由 _audio_play_priority_thread / 速率控制器按真实播放节奏
        发出——文字与语音天然同步，不再出现「文字一瞬间全部冒出来」。
        """
        logger.bind(tag=TAG).debug(f"TTS 句子开始: {text}")
        conn = self.conn
        sentence_id = getattr(conn, "sentence_id", None) if conn is not None else None
        self._emit_caption_sentence(text, sentence_id)

    def _on_tts_complete(self):
        logger.bind(tag=TAG).debug("语音合成完成，所有音频已被接收")
        # 唤醒 finish_session 中等待收尾的线程（此刻剩余音频已全部到达）
        self._complete_event.set()
        # 冲刷编码器缓冲区里剩余的音频帧
        if self.tts_opus_encoder is not None:
            try:
                self.tts_opus_encoder.encode_pcm_to_opus_stream(
                    b"", True, callback=self.handle_opus
                )
            except Exception as e:
                logger.bind(tag=TAG).debug(f"冲刷编码器失败: {e}")
        # 会话收尾：把 before_stop_play_files 中的文件音频一并放出
        try:
            asyncio.run_coroutine_threadsafe(
                self._finalize_session(), loop=self.conn.loop
            )
        except Exception as e:
            logger.bind(tag=TAG).debug(f"finalize session skip: {e}")

    def _on_tts_error(self, message):
        logger.bind(tag=TAG).error(f"语音合成出现异常: {message}")
        # 出错时也要唤醒等待者，避免 finish_session 白等整个超时
        self._complete_event.set()

    async def _finalize_session(self):
        """会话收尾：把剩余音频与 LAST 标记推入播放队列（幂等）"""
        if self._session_finalized:
            return
        self._session_finalized = True
        self._process_before_stop_play_files()

    # ------------------------------------------------------------------
    # 文本处理线程
    # ------------------------------------------------------------------
    def tts_text_priority_thread(self):
        """QwenAudio 单流式 TTS 的文本处理线程。"""
        while not self.conn.stop_event.is_set():
            try:
                message = self.tts_text_queue.get(timeout=1)
                logger.bind(tag=TAG).debug(
                    f"收到TTS任务｜{message.sentence_type.name} ｜ "
                    f"{message.content_type.name} | 会话ID: {self.conn.sentence_id}"
                )

                if message.sentence_type == SentenceType.FIRST:
                    self.conn.client_abort = False

                if self.conn.client_abort:
                    try:
                        logger.bind(tag=TAG).info("收到打断信息，终止TTS文本处理线程")
                        asyncio.run_coroutine_threadsafe(
                            self.cancel_session(self.conn.sentence_id),
                            loop=self.conn.loop,
                        )
                        continue
                    except Exception as e:
                        logger.bind(tag=TAG).error(f"取消TTS会话失败: {str(e)}")
                        continue

                if message.sentence_type == SentenceType.FIRST:
                    # 初始化会话
                    try:
                        if not getattr(self.conn, "sentence_id", None):
                            self.conn.sentence_id = uuid.uuid4().hex
                            logger.bind(tag=TAG).debug(
                                f"自动生成新的 会话ID: {self.conn.sentence_id}"
                            )

                        logger.bind(tag=TAG).debug("开始启动TTS会话...")
                        future = asyncio.run_coroutine_threadsafe(
                            self.start_session(self.conn.sentence_id),
                            loop=self.conn.loop,
                        )
                        future.result(timeout=self.tts_timeout)
                        self.before_stop_play_files.clear()
                        # 字幕不在这里按 LLM 分片下发：服务端会自行断句
                        # （句首事件带原文），由 _on_sentence_begin 按播放节奏下发。
                        logger.bind(tag=TAG).debug("TTS会话启动成功")
                    except Exception as e:
                        logger.bind(tag=TAG).error(f"启动TTS会话失败: {str(e)}")
                        continue

                elif ContentType.TEXT == message.content_type:
                    if message.content_detail:
                        try:
                            logger.bind(tag=TAG).debug(
                                f"开始发送TTS文本: {message.content_detail}"
                            )
                            # 字幕由服务端句首事件驱动（见 _on_sentence_begin），
                            # 此处只负责把文本送进合成器
                            future = asyncio.run_coroutine_threadsafe(
                                self.text_to_speak(message.content_detail, None),
                                loop=self.conn.loop,
                            )
                            future.result(timeout=self.tts_timeout)
                            logger.bind(tag=TAG).debug("TTS文本发送成功")
                        except Exception as e:
                            logger.bind(tag=TAG).error(f"发送TTS文本失败: {str(e)}")
                            continue

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
                    try:
                        logger.bind(tag=TAG).debug("开始结束TTS会话...")
                        # 尾部字幕同样来自服务端句首事件，无需客户端补发
                        future = asyncio.run_coroutine_threadsafe(
                            self.finish_session(self.conn.sentence_id),
                            loop=self.conn.loop,
                        )
                        future.result(timeout=self.tts_timeout)
                    except Exception as e:
                        logger.bind(tag=TAG).error(f"结束TTS会话失败: {str(e)}")
                        continue

            except queue.Empty:
                # 打断后 abortHandle 会先置 client_abort=True 再 clear_queues()，
                # 把 tts_text_queue 清空。本线程因此再也取不到消息，也就永远走
                # 不到上面的 client_abort 分支去 cancel_session()，正在合成的
                # 会话会一直空转，23 秒后被服务端空闲看门狗以
                # task-failed("request timeout after 23 seconds") 掐掉。
                # 所以队列空闲时也要检查打断状态，主动取消当前会话。
                if self.conn.client_abort and self.synthesizer is not None:
                    logger.bind(tag=TAG).info(
                        "队列空闲但处于打断状态，主动取消当前TTS会话"
                    )
                    try:
                        asyncio.run_coroutine_threadsafe(
                            self.cancel_session(self.conn.sentence_id),
                            loop=self.conn.loop,
                        )
                    except Exception as e:
                        logger.bind(tag=TAG).error(f"取消TTS会话失败: {str(e)}")
                continue
            except Exception as e:
                logger.bind(tag=TAG).error(
                    f"处理TTS文本失败: {str(e)}, 类型: {type(e).__name__}, "
                    f"堆栈: {traceback.format_exc()}"
                )
                continue

    async def text_to_speak(self, text, _):
        """把（分句）文本提交给 QwenAudio 流式合成。"""
        try:
            if self.synthesizer is None:
                # 上一轮会话可能已被 LAST 关闭（典型场景：中断恢复
                # 会在 LAST 之后再追加一条 MIDDLE 文本询问用户）。
                # 此时按需重建合成器，避免丢弃该段语音。
                logger.bind(tag=TAG).warning(
                    "TTS合成器不存在，正在重建会话后继续发送文本"
                )
                sid = getattr(self.conn, "sentence_id", None)
                if sid:
                    await self.start_session(sid)
                if self.synthesizer is None:
                    logger.bind(tag=TAG).error(
                        "重建TTS合成器失败，终止发送文本"
                    )
                    return

            filtered_text = MarkdownCleaner.clean_markdown(text)
            if not filtered_text:
                return

            # streaming_call 是阻塞在内部线程上的调用（第一次会建连），
            # 这里放到独立线程里跑，避免阻塞事件循环；SDK 回调会把音频推回。
            await asyncio.get_running_loop().run_in_executor(
                None, self._submit_text, filtered_text
            )
        except Exception as e:
            logger.bind(tag=TAG).error(f"发送TTS文本失败: {str(e)}")
            await self._close_synthesizer()
            raise

    def _submit_text(self, text: str):
        """在 executor 线程内同步调用 SDK 的流式接口。"""
        self.synthesizer.streaming_call(text)

    # ------------------------------------------------------------------
    # 文件音频：使用独立编码器，避免与 TTS 编码线程并发冲突
    # ------------------------------------------------------------------
    def audio_to_opus_data_stream(
        self, audio_file_path, callback: Callable[[Any], Any] = None
    ):
        """重写父类方法：使用独立的临时编码器处理音频文件，避免与TTS流式编码器并发冲突。"""
        from core.utils.util import audio_to_data_stream

        return audio_to_data_stream(
            audio_file_path,
            is_opus=True,
            callback=callback,
            sample_rate=self.conn.sample_rate,
            opus_encoder=None,
        )

    # ------------------------------------------------------------------
    # 非流式 TTS（生成音频文件 / 测试场景）
    # ------------------------------------------------------------------
    def to_tts(self, text: str) -> list:
        """非流式生成音频数据，用于生成音频及测试场景。"""
        if not _DASHSCOPE_AVAILABLE:
            logger.bind(tag=TAG).error("dashscope SDK 不可用，无法生成音频")
            return []
        audio_data: list = []
        try:
            # 需要一个 sample_rate 供 _build_audio_format 使用；
            # 非流式场景下没有 conn，退化为默认 16000。
            sample_rate = getattr(self.conn, "sample_rate", 16000)
            audio_format = self._build_audio_format(sample_rate)

            if self.tts_opus_encoder is None:
                self.tts_opus_encoder = opus_encoder_utils.OpusEncoderUtils(
                    sample_rate=sample_rate, channels=1, frame_size_ms=60
                )

            collected_pcm: list = []

            class _Collector(ResultCallback):
                def on_data(self, data: bytes) -> None:
                    collected_pcm.append(bytes(data))

                def on_complete(self) -> None:
                    logger.bind(tag=TAG).debug("非流式合成完成")

                def on_error(self, message: str) -> None:
                    logger.bind(tag=TAG).error(f"非流式合成异常: {message}")

            synthesizer = SpeechSynthesizer(
                model=self.model,
                voice=self.voice,
                format=audio_format,
                volume=self.volume,
                speech_rate=self.speech_rate,
                pitch_rate=self.pitch_rate,
                headers={"X-DashScope-DataInspection": "enable"},
                callback=_Collector(),
                workspace=self.workspace,
            )
            try:
                synthesizer.call(
                    MarkdownCleaner.clean_markdown(text),
                    timeout_millis=int(self.tts_timeout * 1000),
                )
                # 把累计的 PCM 编码成 Opus 帧
                for pcm in collected_pcm:
                    self.tts_opus_encoder.encode_pcm_to_opus_stream(
                        pcm,
                        False,
                        callback=lambda frame: audio_data.append(frame),
                    )
                self.tts_opus_encoder.encode_pcm_to_opus_stream(
                    b"", True, callback=lambda frame: audio_data.append(frame)
                )
            finally:
                try:
                    synthesizer.close()
                except Exception:
                    pass

            return audio_data
        except Exception as e:
            logger.bind(tag=TAG).error(f"生成音频数据失败: {str(e)}")
            return []


class _QwenAudioCallback(ResultCallback):
    """把 DashScope SDK 回调桥接到 TTSProvider 的处理方法上。"""

    def __init__(self, tag, on_audio, on_complete, on_error, on_sentence):
        self._tag = tag
        self._on_audio = on_audio
        self._on_complete = on_complete
        self._on_error = on_error
        self._on_sentence = on_sentence

    def on_open(self) -> None:
        pass

    def on_data(self, data: bytes) -> None:
        self._on_audio(data)

    def on_complete(self) -> None:
        self._on_complete()

    def on_close(self) -> None:
        pass

    def on_event(self, message: str) -> None:
        """服务端事件：句首事件携带该句原文，用于驱动字幕下发。"""
        try:
            data = json.loads(message)
            output = data.get("payload", {}).get("output", {})
            event_type = output.get("type", "")
            original_text = output.get("original_text", "")
        except Exception:
            return
        if not event_type:
            return
        logger.bind(tag=self._tag).debug(
            f"TTS事件类型: {event_type}, 原始文本: {original_text}"
        )
        # 仅用句首事件驱动字幕：它与该句音频帧几乎同时到达且先于音频帧，
        # 因此字幕会被排在这句话的音频之前，由播放线程按播放节奏发出。
        if event_type == SENTENCE_BEGIN_EVENT and original_text:
            self._on_sentence(original_text)

    def on_error(self, message) -> None:
        self._on_error(message)

# coding=utf-8
"""Fun-ASR Realtime Flash 双向流式 ASR Provider。

使用阿里云百炼（DashScope）的 Realtime Recognition API（fun-asr-realtime /
fun-asr-flash）通过 WebSocket 双向流式识别麦克风音频。

架构要点：
- 使用 dashscope.audio.asr.Recognition + RecognitionCallback。SDK 内部使用
  自有线程处理 WebSocket；音频帧通过 send_audio_frame 推入，结果通过回调
  on_event 推回。回调在 SDK 线程上执行，需要把所有与事件循环相关的操作
  通过 asyncio.run_coroutine_threadsafe 转发到 conn.loop。
- 识别结果（部分结果 / 最终句）在回调中累积，speech_to_text 直接从
  self.text 取出并清空，与 aliyunbl_stream.py 保持一致。
- 手动模式（client_listen_mode=manual）下，音频停止后才结束会话；
  自动模式下，一旦收到 sentence_end 的最终结果就触发 handle_voice_stop，
  与 aliyunbl_stream 一致。
"""

import os
import json
import uuid
import queue
import asyncio
import traceback
import threading
from typing import List, TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

import opuslib_next
import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

from config.logger import setup_logging
from core.providers.asr.base import ASRProviderBase
from core.providers.asr.dto.dto import InterfaceType

TAG = __name__
logger = setup_logging()


class _RecognitionBridge(RecognitionCallback):
    """把 SDK 回调桥接到 ASRProvider 上。

    回调运行在 SDK 内部线程，因此必须通过 run_coroutine_threadsafe
    把结果处理转回事件循环，避免跨线程直接调用 asyncio API。
    """

    def __init__(self, provider: "ASRProvider"):
        self._provider = provider

    def _is_active(self) -> bool:
        """忽略已清理或已被新会话替换的 SDK 回调。"""
        provider = self._provider
        return provider._bridge is self and provider._recognition is not None

    def on_open(self) -> None:
        if not self._is_active():
            return
        self._provider.server_ready = True
        logger.bind(tag=TAG).debug("Fun-ASR 连接已建立，开始转发缓存音频")

        # 把缓存音频补发给识别器
        p = self._provider
        for cached in list(p._cached_audio):
            try:
                pcm = p.decoder.decode(cached, 960)
                p._recognition.send_audio_frame(pcm)
            except Exception as e:
                logger.bind(tag=TAG).warning(f"补发缓存音频失败: {e}")
                break
        p._cached_audio.clear()

    def on_complete(self) -> None:
        if not self._is_active():
            return
        logger.bind(tag=TAG).debug("Fun-ASR 识别完成")
        # 触发 handle_voice_stop；必须在事件循环上执行
        p = self._provider
        try:
            asyncio.run_coroutine_threadsafe(
                p._finalize_and_report(), loop=p._conn.loop
            )
        except Exception as e:
            logger.bind(tag=TAG).debug(f"finalize 跳过: {e}")

    def on_error(self, result: RecognitionResult) -> None:
        if not self._is_active():
            logger.bind(tag=TAG).debug("忽略已关闭 Fun-ASR 会话的迟到错误回调")
            return
        try:
            logger.bind(tag=TAG).error(
                f"Fun-ASR 识别异常: status={result.status_code}, "
                f"code={result.code}, msg={result.message}"
            )
        except Exception:
            logger.bind(tag=TAG).error(f"Fun-ASR 识别异常（详细信息不可用）")

        # 错误后必须清理会话状态，否则 is_processing 会一直为 True，
        # 导致后续音频帧无法触发新的 _start_recognition（receive_audio
        # 以 not self.is_processing 为守卫），陈旧连接也会反复超时。
        # 回调运行在 SDK 内部线程，清理动作放到事件循环上执行。
        p = self._provider
        coro = p._cleanup_async()
        try:
            asyncio.run_coroutine_threadsafe(coro, loop=p._conn.loop)
        except Exception:
            # 事件循环不可用时（如连接正在关闭），直接同步清理
            coro.close()
            p._cleanup()

    def on_close(self) -> None:
        logger.bind(tag=TAG).debug("Fun-ASR 连接已关闭")

    def on_event(self, result: RecognitionResult) -> None:
        """处理单句识别结果（部分 / 最终）。"""
        if not self._is_active():
            return
        sentence = result.get_sentence()
        if not sentence:
            return
        # 忽略心跳
        if sentence.get("heartbeat"):
            return

        text = (sentence.get("text") or "").strip()
        is_final = RecognitionResult.is_sentence_end(sentence)
        if not text:
            return

        p = self._provider
        # 把部分结果 / 最终结果累积到 self.text；
        # 与 aliyunbl_stream 一致，手动模式在语音停止信号到达后才真正处理。
        if is_final:
            p._last_final_text = text
            logger.bind(tag=TAG).info(f"Fun-ASR 最终识别: {text}")
        else:
            p._last_partial_text = text
            logger.bind(tag=TAG).debug(f"Fun-ASR 部分识别: {text}")

        # 自动模式（streaming）：一旦有最终结果立即触发语音停止处理
        conn = p._conn
        if conn is not None and getattr(conn, "client_listen_mode", "auto") != "manual":
            if is_final:
                try:
                    asyncio.run_coroutine_threadsafe(
                        p._finalize_and_report(), loop=conn.loop
                    )
                except Exception as e:
                    logger.bind(tag=TAG).debug(f"auto 模式 finalize 跳过: {e}")


class ASRProvider(ASRProviderBase):
    def __init__(self, config: dict, delete_audio_file: bool):
        super().__init__()
        self.interface_type = InterfaceType.STREAM

        self.config = config
        self.delete_audio_file = delete_audio_file
        self.output_dir = config.get("output_dir", "tmp/")
        os.makedirs(self.output_dir, exist_ok=True)

        # 百炼配置
        # WebSocket URL
        self.base_websocket_api_url = config.get("base_websocket_api_url", "wss://ws-lahnz1fxxpirg9zl.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference")
        dashscope.base_websocket_api_url = self.base_websocket_api_url

        self.api_key = config.get("api_key")
        # 模型：默认使用 qwen 通义千问 3 Flash 实时语音识别
        self.model = config.get("model", "fun-asr-flash-2026-06-15")
        self.sample_rate = int(config.get("sample_rate", 16000))
        self.format = config.get("format", "pcm")

        # 可选参数
        self.vocabulary_id = config.get("vocabulary_id")
        self.language_hints = config.get("language_hints")  # 可选: ["zh", "en"]
        self.disfluency_removal_enabled = bool(
            config.get("disfluency_removal_enabled", False)
        )
        self.punctuation_prediction_enabled = bool(
            config.get("punctuation_prediction_enabled", True)
        )
        self.semantic_punctuation_enabled = bool(
            config.get("semantic_punctuation_enabled", False)
        )
        self.max_sentence_silence = int(config.get("max_sentence_silence", 200))
        self.multi_threshold_mode_enabled = bool(
            config.get("multi_threshold_mode_enabled", False)
        )

        # 运行时状态
        self.decoder = opuslib_next.Decoder(self.sample_rate, 1)
        self.text: str = ""
        self._last_final_text: str = ""
        self._last_partial_text: str = ""

        self._recognition: Optional[Recognition] = None
        self._bridge: Optional[_RecognitionBridge] = None
        self._conn: Optional["ConnectionHandler"] = None
        self.is_processing: bool = False
        self.server_ready: bool = False
        self._cached_audio: List[bytes] = []
        self._stopped_flag = threading.Event()
        self._reported = False

    # ------------------------------------------------------------------
    # 事件循环侧：会话生命周期
    # ------------------------------------------------------------------
    async def open_audio_channels(self, conn: "ConnectionHandler"):
        await super().open_audio_channels(conn)
        self._conn = conn
        self.is_processing = False
        self.server_ready = False
        self._stopped_flag.clear()
        self._reported = False

    async def receive_audio(self, conn, audio, audio_have_voice):
        # 先执行父类逻辑（缓存 / VAD 等）
        await super().receive_audio(conn, audio, audio_have_voice)

        # 本地 VAD（或设备端 listen stop）判定「一句话说完」：结束识别会话并交付结果。
        #
        # 自动模式也必须处理。原因：本地 VAD 一旦转为无语音，下面的分支就不再
        # 发送音频帧；DashScope 服务端因此看不到尾部静音，无法自行断句，会话会
        # 一直空转，23 秒后被 SDK 的静音看门狗清理并报错
        # （request timeout after 23 seconds / Idle timeout!），随后
        # send_audio_frame 还会抛 "Speech recognition has stopped."；
        # 空转期间 is_processing 守卫也让下一次识别无法开始。
        if self.is_processing and getattr(conn, "client_voice_stop", False):
            conn.client_voice_stop = False  # 消费后清除，避免误杀下一个会话
            logger.bind(tag=TAG).debug("收到语音停止信号，结束识别会话")
            self._mark_stop()
            # 立即触发收尾：_finalize_and_report 内部的 _cleanup 会 stop() 掉
            # 识别会话，不再等待 SDK 静音超时
            asyncio.create_task(self._finalize_and_report())

        # 没有声音且当前没识别中：把新帧作为"起始缓存"
        if not audio_have_voice:
            if not self.is_processing:
                # 保留最后 10 帧作为补发的"前导"缓存
                self._cached_audio = (list(conn.asr_audio or []) + [audio])[-10:]
            return

        # 有声音且未识别中：启动识别会话
        if audio_have_voice and not self.is_processing:
            try:
                await self._start_recognition(conn)
            except Exception as e:
                logger.bind(tag=TAG).error(f"启动识别失败: {e}")
                self._cleanup()
                return

        # 已识别中：把解码后的 PCM 推给 SDK 识别器
        if self.is_processing and self.server_ready and self._recognition is not None:
            try:
                pcm = self.decoder.decode(audio, 960)
                self._recognition.send_audio_frame(pcm)
            except opuslib_next.OpusError as e:
                logger.bind(tag=TAG).debug(f"解码失败（忽略）: {e}")
            except Exception as e:
                logger.bind(tag=TAG).error(f"发送音频帧失败: {e}")
                self._cleanup()

    async def _start_recognition(self, conn: "ConnectionHandler"):
        """建立新的 Fun-ASR 识别会话。"""
        self._conn = conn
        self.is_processing = True
        self.server_ready = False
        self._last_final_text = ""
        self._last_partial_text = ""
        self._stopped_flag.clear()
        self._reported = False
        # 丢弃上一轮可能残留的停止标记，避免新会话刚建立就被立刻收尾
        conn.client_voice_stop = False

        # 手动模式下把断句阈值放到最大
        if getattr(conn, "client_listen_mode", "auto") == "manual":
            self.max_sentence_silence = 6000

        dashscope.api_key = self.api_key

        self._bridge = _RecognitionBridge(self)
        kwargs = {
            "disfluency_removal_enabled": self.disfluency_removal_enabled,
            "punctuation_prediction_enabled": self.punctuation_prediction_enabled,
            "semantic_punctuation_enabled": self.semantic_punctuation_enabled,
            "max_sentence_silence": self.max_sentence_silence,
            "multi_threshold_mode_enabled": self.multi_threshold_mode_enabled,
        }
        if self.language_hints:
            kwargs["language_hints"] = self.language_hints
        if self.vocabulary_id:
            kwargs["vocabulary_id"] = self.vocabulary_id

        self._recognition = Recognition(
            model=self.model,
            callback=self._bridge,
            format=self.format,
            sample_rate=self.sample_rate,
            **kwargs,
        )

        try:
            self._recognition.start(phrase_id=self.vocabulary_id)
        except Exception:
            # start 失败，回收资源
            self._recognition = None
            raise

        logger.bind(tag=TAG).debug(
            f"Fun-ASR 会话已启动: model={self.model}, "
            f"sample_rate={self.sample_rate}, format={self.format}"
        )

    def _mark_stop(self):
        """标记停止：让 _finalize_and_report 知道可以走 handle_voice_stop。"""
        self._stopped_flag.set()

    async def _finalize_and_report(self):
        """把最后一次识别结果交给 handle_voice_stop。

        幂等：同一会话只上报一次，避免自动模式下两个 final 结果
        （on_event 与 on_complete）导致重复 handle_voice_stop / 重复 LLM 回复。
        """
        if self._conn is None or self._reported:
            return
        self._reported = True

        conn = self._conn
        # 决定要发送的文本：优先用最终结果，否则用最后一次部分结果
        final = self._last_final_text or self._last_partial_text
        if not final:
            logger.bind(tag=TAG).debug("无识别结果，跳过语音停止处理")
            await self._cleanup_async()
            return

        # 手动模式累积，自动模式覆盖
        if getattr(conn, "client_listen_mode", "auto") == "manual":
            self.text = self.text + final if self.text else final
        else:
            self.text = final

        # 把缓存的音频交给 handle_voice_stop 统一处理（父类会走 ASR 上报 / LLM 路由）
        audio_snapshot = list(getattr(conn, "asr_audio", []) or [])
        if audio_snapshot:
            try:
                await self.handle_voice_stop(conn, audio_snapshot)
            except Exception as e:
                logger.bind(tag=TAG).error(f"handle_voice_stop 失败: {e}")

        await self._cleanup_async()

    async def _send_stop_request(self):
        """手动模式下，设备发送 listen state=stop 时由 listenMessageHandler 调用。

        停止 SDK 识别会话；随后 _finalize_and_report 由 on_complete 回调触发，
        把累积的文本交付给 handle_voice_stop。
        """
        logger.bind(tag=TAG).debug("手动模式：发送停止请求")
        self._mark_stop()
        if self._recognition is not None:
            try:
                self._recognition.stop()
            except Exception as e:
                logger.bind(tag=TAG).debug(f"stop 跳过: {e}")

    @staticmethod
    def _stop_recognition(recognition):
        if recognition is not None:
            try:
                recognition.stop()
            except Exception as e:
                logger.bind(tag=TAG).debug(f"stop 跳过: {e}")

    def _cleanup(self):
        """同步清理 SDK 识别器；仅供同步线程或关闭兜底路径调用。"""
        self.is_processing = False
        self.server_ready = False
        rec = self._recognition
        self._recognition = None
        self._bridge = None
        self._stop_recognition(rec)

    async def _cleanup_async(self):
        """清理会话状态，并在线程池停止可能阻塞的 SDK 工作线程。"""
        self.is_processing = False
        self.server_ready = False
        rec = self._recognition
        self._recognition = None
        self._bridge = None
        await asyncio.to_thread(self._stop_recognition, rec)

    async def close(self):
        """资源清理。"""
        self._cleanup()
        self._conn = None

    def stop_ws_connection(self):
        """基类在语音停止处理完成后调用。"""
        self._cleanup()

    # ------------------------------------------------------------------
    # 结果交付
    # ------------------------------------------------------------------
    async def speech_to_text(
        self,
        opus_data: List[bytes],
        session_id: str,
        audio_format: str = "opus",
        artifacts=None,
    ) -> tuple:
        """直接返回缓存中的识别结果。与 aliyunbl_stream 一致。"""
        result = self.text
        self.text = ""
        return result, None

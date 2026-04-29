import ssl
import json
import asyncio
import websockets

from config.logger import setup_logging
from typing import Optional, Tuple, List
from core.providers.asr.base import ASRProviderBase
from core.providers.asr.utils import lang_tag_filter
from core.providers.asr.dto.dto import InterfaceType

TAG = __name__
logger = setup_logging()


class ASRProvider(ASRProviderBase):
    def __init__(self, config: dict, delete_audio_file: bool):
        """
        Initialize the ASRProvider with server configuration.
        :param config: Dictionary containing 'host', 'port', and 'is_ssl'.
        :param delete_audio_file: Boolean to indicate whether to delete audio files after processing.
        """
        super().__init__()
        self.interface_type = InterfaceType.NON_STREAM
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 10091)
        self.api_key = config.get("api_key", "none")
        self.is_ssl = str(config.get("is_ssl", True)).lower() in (
            "true",
            "1",
            "yes",
        )
        self.output_dir = config.get("output_dir")
        self.delete_audio_file = delete_audio_file
        self.uri = (
            f"wss://{self.host}:{self.port}/v1/asr"
            if self.is_ssl
            else f"ws://{self.host}:{self.port}/v1/asr"
        )
        self.ssl_context = ssl.SSLContext() if self.is_ssl else None
        if self.ssl_context:
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

    async def _receive_responses(self, ws) -> None:
        """
        Asynchronous generator to receive messages from the WebSocket.
        Yields each message as it is received.
        """
        text = ""
        while True:
            try:
                # 【关键】设置 50 秒超时，等待服务端处理完成
                response = await asyncio.wait_for(ws.recv(), timeout=50)
                response_data = json.loads(response)
                logger.bind(tag=TAG).debug(f"Received response: {response_data}")
                if response_data.get("is_final", True):
                    text += response_data.get("text", "")
                    break
                else:
                    text += response_data.get("text", "")
            except asyncio.TimeoutError:
                logger.bind(tag=TAG).error(
                    "Timeout while waiting for response from WebSocket."
                )
                break
            except websockets.exceptions.ConnectionClosed as e:
                logger.bind(tag=TAG).error(f"WebSocket connection closed: {e}")
                break
        return text

    async def _send_data(self, ws, pcm_data: bytes, session_id: str) -> tuple:
        """
        Internal method to handle WebSocket communication.
        Reuses the persistent WebSocket connection if available.
        :param pcm_data: PCM audio data to send.
        :param session_id: Unique session identifier.
        :return: Tuple containing recognized text and optional timestamp.
        """

        # Send initial configuration message
        config_message = json.dumps(
            {
                "mode": "offline",
                "chunk_size": [5, 10, 5],
                "chunk_interval": 10,
                "wav_name": session_id,
                "is_speaking": True,
                "itn": False,
            }
        )
        await ws.send(config_message)
        logger.bind(tag=TAG).debug(f"Sent configuration message: {config_message}")

        # Send PCM data
        await ws.send(pcm_data)
        logger.bind(tag=TAG).debug(f"Sent PCM data of length: {len(pcm_data)} bytes")

        # Indicate end of speech
        end_message = json.dumps({"is_speaking": False})
        await ws.send(end_message)
        logger.bind(tag=TAG).debug(f"Sent end message: {end_message}")

    async def speech_to_text(
            self, opus_data: List[bytes], session_id: str, audio_format="opus", artifacts=None
    ) -> Tuple[Optional[str], Optional[str]]:
        if artifacts is None:
            return "", None

        auth_header = {"Authorization": "Bearer; {}".format(self.api_key)}
        async with websockets.connect(
                self.uri,
                additional_headers=auth_header,
                subprotocols=["binary"],
                ping_interval=None,
                ssl=self.ssl_context,
        ) as ws:
            try:
                # 【关键】先发送，确保发完再接收
                await self._send_data(ws, artifacts.pcm_bytes, session_id)
                # 发送完再等结果
                result = await self._receive_responses(ws)

                result = lang_tag_filter(result)
                return result, artifacts.file_path

            except websockets.exceptions.ConnectionClosed as e:
                logger.bind(tag=TAG).error(f"WebSocket connection closed: {e}")
                return "", artifacts.file_path
            except Exception as e:
                logger.bind(tag=TAG).error(f"Error: {e}", exc_info=True)
                return "", artifacts.file_path

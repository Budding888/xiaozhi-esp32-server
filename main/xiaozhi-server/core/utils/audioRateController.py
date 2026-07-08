import time
import asyncio
from collections import deque
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class AudioRateController:
    """
    音频速率控制器 - 按照60ms帧时长精确控制音频发送
    解决高并发下的时间累积误差问题
    """

    def __init__(self, frame_duration=60):
        """
        Args:
            frame_duration: 单个音频帧时长（毫秒），默认60ms
        """
        self.frame_duration = frame_duration
        self.queue = deque()
        self.play_position = 0  # 虚拟播放位置（毫秒）
        self.start_timestamp = None  # 开始时间戳（只读，不修改）
        self.pending_send_task = None
        self.logger = logger
        self.queue_empty_event = asyncio.Event()  # 队列清空事件
        self.queue_empty_event.set()  # 初始为空状态
        self.queue_has_data_event = asyncio.Event()  # 队列数据事件
        self._last_queue_empty_time = 0  # 上次队列清空的时间（秒）

    def reset(self):
        """重置控制器状态"""
        if self.pending_send_task and not self.pending_send_task.done():
            self.pending_send_task.cancel()
            # 取消任务后，任务会在下次事件循环时清理，无需阻塞等待

        self.queue.clear()
        self.play_position = 0
        self.start_timestamp = None  # 由首个音频包设置
        self._last_queue_empty_time = 0  # 重置时间
        # 相关事件处理
        self.queue_empty_event.set()
        self.queue_has_data_event.clear()

    def add_audio(self, opus_packet):
        """添加音频包到队列"""
        self._ensure_sending()

        # 如果队列之前为空，需要调整时间戳以保持播放时间连续
        # 这样工具调用等待期间，新加入的音频不会提前播放
        # 如果间隔很短（<1帧），说明是正常的流式传输，不需要重置
        if len(self.queue) == 0 and self.play_position > 0:
            elapsed_since_empty = (time.monotonic() - self._last_queue_empty_time) * 1000
            # 只有间隔超过1帧时长，才认为是真正的"暂停恢复"
            if elapsed_since_empty >= self.frame_duration:
                self.start_timestamp = time.monotonic() - (self.play_position / 1000)
                self.logger.bind(tag=TAG).debug(
                    f"队列从空恢复，重置时间戳，当前播放位置: {self.play_position}ms，间隔: {elapsed_since_empty:.0f}ms"
                )

        self.queue.append(("audio", opus_packet))
        # 相关事件处理
        self.queue_empty_event.clear()
        self.queue_has_data_event.set()

    def add_message(self, message_callback):
        """
        添加消息到队列（立即发送，不占用播放时间）

        Args:
            message_callback: 消息发送回调函数 async def()
        """
        self._ensure_sending()

        if len(self.queue) == 0 and self.play_position > 0:
            elapsed_since_empty = (time.monotonic() - self._last_queue_empty_time) * 1000
            if elapsed_since_empty >= self.frame_duration:
                self.start_timestamp = time.monotonic() - (self.play_position / 1000)
                self.logger.bind(tag=TAG).debug(
                    f"队列从空恢复，重置时间戳，当前播放位置: {self.play_position}ms，间隔: {elapsed_since_empty:.0f}ms"
                )

        self.queue.append(("message", message_callback))
        # 相关事件处理
        self.queue_empty_event.clear()
        self.queue_has_data_event.set()

    def _get_elapsed_ms(self):
        """获取已经过的时间（毫秒）"""
        if self.start_timestamp is None:
            return 0
        return (time.monotonic() - self.start_timestamp) * 1000

    async def check_queue(self, send_audio_callback):
        """
        检查队列并按时发送音频/消息

        Args:
            send_audio_callback: 发送音频的回调函数 async def(opus_packet)
        """
        while self.queue:
            item = self.queue[0]
            item_type = item[0]

            if item_type == "message":
                # 消息类型：立即发送，不占用播放时间
                _, message_callback = item
                try:
                    await message_callback()
                except Exception as e:
                    self.logger.bind(tag=TAG).error(f"发送消息失败: {e}")
                    raise
                finally:
                    self.queue.popleft()

            elif item_type == "audio":
                if self.start_timestamp is None:
                    self.start_timestamp = time.monotonic()

                _, opus_packet = item

                # 循环等待直到时间到达
                while True:
                    # 计算时间差
                    elapsed_ms = self._get_elapsed_ms()
                    output_ms = self.play_position

                    if elapsed_ms < output_ms:
                        # 还不到发送时间，计算等待时长
                        wait_ms = output_ms - elapsed_ms

                        # 等待后继续检查（允许被中断）
                        try:
                            await asyncio.sleep(wait_ms / 1000)
                        except asyncio.CancelledError:
                            self.logger.bind(tag=TAG).debug("音频发送任务被取消")
                            raise
                        # 等待结束后重新检查时间（循环回到 while True）
                    else:
                        # 时间已到，跳出等待循环
                        break

                # 时间已到，先递增播放位置再发送，finally 中出队
                self.play_position += self.frame_duration
                try:
                    await send_audio_callback(opus_packet)
                except Exception as e:
                    self.logger.bind(tag=TAG).error(f"发送音频失败: {e}")
                    raise
                finally:
                    self.queue.popleft()

        # 队列处理完后清除事件
        self.queue_empty_event.set()
        self.queue_has_data_event.clear()
        self._last_queue_empty_time = time.monotonic()  # 记录队列清空时间

    def _ensure_sending(self):
        """
        确保后台发送循环正在运行。
        检测发送任务是否存活，若停止则自动重启。
        在 add_audio() 和 add_message() 开头调用。
        """
        if not getattr(self, '_send_callback', None):
            return  # 尚未初始化，跳过

        task_alive = (
            hasattr(self, 'pending_send_task')
            and self.pending_send_task is not None
            and not self.pending_send_task.done()
        )

        if not task_alive:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                return

            if loop.is_running():
                self.logger.bind(tag=TAG).warning("发送循环已停止，自动重启...")
                self.pending_send_task = asyncio.create_task(self._run_send_loop())

    async def _run_send_loop(self):
        """
        持续运行的音频发送循环。
        异常时不退出，仅主动取消时退出。
        """
        while True:
            try:
                await self.queue_has_data_event.wait()
                await self.check_queue(self._send_callback)
            except asyncio.CancelledError:
                self.logger.bind(tag=TAG).debug("音频发送循环已主动停止")
                break
            except Exception as e:
                self.logger.bind(tag=TAG).error(
                    f"音频发送循环异常，自动恢复: {e}"
                )
                await asyncio.sleep(0.1)
                continue

    def start_sending(self, send_audio_callback):
        """
        启动异步发送任务

        Args:
            send_audio_callback: 发送音频的回调函数

        Returns:
            asyncio.Task: 发送任务
        """
        self._send_callback = send_audio_callback
        self.pending_send_task = asyncio.create_task(self._run_send_loop())
        return self.pending_send_task

    def stop_sending(self):
        """停止发送任务"""
        if self.pending_send_task and not self.pending_send_task.done():
            self.pending_send_task.cancel()
            self.logger.bind(tag=TAG).debug("已取消音频发送任务")

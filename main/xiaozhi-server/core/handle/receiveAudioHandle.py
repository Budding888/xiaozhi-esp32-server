import time
import json
import uuid
import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler
from core.utils.util import audio_to_data
from core.handle.abortHandle import handleAbortMessage
from core.handle.intentHandler import handle_user_intent
from core.utils.output_counter import check_device_output_limit
from core.handle.sendAudioHandle import send_stt_message, SentenceType

TAG = __name__


async def handleAudioMessage(conn: "ConnectionHandler", audio):
    if conn.is_exiting:
        return
    # 当前片段是否有人说话
    have_voice = conn.vad.is_vad(conn, audio)
    # 如果设备刚刚被唤醒，短暂忽略VAD检测
    if hasattr(conn, "just_woken_up") and conn.just_woken_up:
        have_voice = False
        # 设置一个短暂延迟后恢复VAD检测
        if not hasattr(conn, "vad_resume_task") or conn.vad_resume_task.done():
            conn.vad_resume_task = asyncio.create_task(resume_vad_detection(conn))
        return
    # manual 模式下不打断正在播放的内容
    if have_voice:
        if conn.client_is_speaking and conn.client_listen_mode != "manual":
            await handleAbortMessage(conn)
    # 设备长时间空闲检测，用于say goodbye
    await no_voice_close_connect(conn, have_voice)
    # 接收音频
    await conn.asr.receive_audio(conn, audio, have_voice)


async def resume_vad_detection(conn: "ConnectionHandler"):
    # 等待2秒后恢复VAD检测
    await asyncio.sleep(2)
    conn.just_woken_up = False


async def startToChat(conn: "ConnectionHandler", text):
    # 检查输入是否是JSON格式（包含说话人信息）
    speaker_name = None
    language_tag = None
    actual_text = text

    try:
        # 尝试解析JSON格式的输入
        if text.strip().startswith("{") and text.strip().endswith("}"):
            data = json.loads(text)
            if "speaker" in data and "content" in data:
                speaker_name = data["speaker"]
                language_tag = data["language"]
                actual_text = data["content"]
                conn.logger.bind(tag=TAG).info(f"解析到说话人信息: {speaker_name}")

                # 直接使用JSON格式的文本，不解析
                actual_text = text
    except (json.JSONDecodeError, KeyError):
        # 如果解析失败，继续使用原始文本
        pass

    # 保存说话人信息到连接对象
    if speaker_name:
        conn.current_speaker = speaker_name
    else:
        conn.current_speaker = None

    if conn.need_bind:
        await check_bind_device(conn)
        return

    # 如果当日的输出字数大于限定的字数
    if conn.max_output_size > 0:
        if check_device_output_limit(
            conn.headers.get("device-id"), conn.max_output_size
        ):
            await max_out_size(conn)
            return
    # manual 模式下不打断正在播放的内容
    if conn.client_is_speaking and conn.client_listen_mode != "manual":
        await handleAbortMessage(conn)

    # ===== 医疗入口预过滤器（最高优先级） =====
    # 在意图分析和LLM调用之前，直接通过关键词拦截医疗问题
    # 彻底避开 intent_type / func_handler 初始化时序问题
    if hasattr(conn, '_is_medical_query') and conn._is_medical_query(actual_text):
        conn.logger.bind(tag=TAG).info(f"===========医疗入口拦截===========: {actual_text}")
        conn.sentence_id = str(uuid.uuid4().hex)
        await send_stt_message(conn, actual_text)
        # search_medical_question 含同步HTTP调用，使用线程池执行
        conn.executor.submit(_direct_medical_and_speak, conn, actual_text)
        return

    # 首先进行意图分析，使用实际文本内容
    intent_handled = await handle_user_intent(conn, actual_text)

    if intent_handled:
        # 如果意图已被处理，不再进行聊天
        return

    # 意图未被处理，继续常规聊天流程，使用实际文本内容
    await send_stt_message(conn, actual_text)
    conn.executor.submit(conn.chat, actual_text)


def _direct_medical_and_speak(conn: "ConnectionHandler", text: str):
    """
    直接执行医疗问答并输出语音（在 executor 线程池中运行）

    被医疗入口预过滤器调用，完全绕过 LLM function_call 决策。
    TTS 内容输出由 search_medical_question 内部处理（RAGFlow 路径直接送入、MedicalQwen 路径流式送入）。
    """
    from plugins_func.functions.search_medical_question import search_medical_question, _send_disclaimer_tts
    from plugins_func.register import Action
    from core.providers.tts.dto.dto import ContentType, TTSMessageDTO, SentenceType
    from core.utils.dialogue import Message

    conn.logger.bind(tag=TAG).info(f"===========直接执行医疗问答并输出语音===========: {text}")

    # FIRST 标记：启动 TTS 处理
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=conn.sentence_id,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
    )

    # 调用 search_medical_question 插件（内容流式输出在内部处理）
    try:
        result = search_medical_question(conn, question=text)
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"search_medical_question 异常: {e}")
        result = None

    # 提取输出文本用于对话记录
    is_error = True
    output = "医疗系统繁忙，请稍后再试"
    if result:
        if result.action == Action.RESPONSE:
            output = result.response or result.result or output
            # RESPONSE 类型：降级路径或错误消息，需要手动 TTS 播报
            conn.tts.tts_one_sentence(
                conn, ContentType.TEXT, content_detail=output
            )
            # 判断是否为真正的错误消息（非降级成功）
            is_error = ("医疗系统繁忙" in output or "请稍后再试" in output or not output)
        elif result.action == Action.REQLLM and result.result:
            output = result.result.strip()
            # REQLLM类型：手动 TTS 播报 知识库与医疗大模型的融合结果
            # V2 的 _call_medical_qwen_v2_no_stream 不流式输出 TTS，融合后的答案需要通过此处播报
            conn.tts.tts_one_sentence(
                conn, ContentType.TEXT, content_detail=output
            )
            is_error = False

    # LAST 标记：结束 TTS 处理
    # 先发送免责声明（独立 TTS 消息，带停顿），再发 LAST 结束标记
    # 免责声明作为独立的 TTS 消息发送，time.sleep(1) 让消费者线程在队列空时自然停顿，形成"回答结束 → 停顿 → 温馨提示"的播报节奏。
    if not is_error:
        _send_disclaimer_tts(conn)
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=conn.sentence_id,
            sentence_type=SentenceType.LAST,
            content_type=ContentType.ACTION,
        )
    )

    # 记录对话
    conn.tts_MessageText = output
    conn.dialogue.put(Message(role="assistant", content=output))
    conn.logger.bind(tag=TAG).info(f"===========医疗问答语音输出完成(is_error={is_error})===========")


async def no_voice_close_connect(conn: "ConnectionHandler", have_voice):
    if have_voice:
        conn.last_activity_time = time.time() * 1000
        return
    # 只有在已经初始化过时间戳的情况下才进行超时检查
    if conn.last_activity_time > 0.0:
        no_voice_time = time.time() * 1000 - conn.last_activity_time
        close_connection_no_voice_time = int(
            conn.config.get("close_connection_no_voice_time", 120)
        )
        if (
            not conn.close_after_chat
            and no_voice_time > 1000 * close_connection_no_voice_time
        ):
            conn.close_after_chat = True
            conn.client_abort = False
            end_prompt = conn.config.get("end_prompt", {})
            if end_prompt and end_prompt.get("enable", True) is False:
                conn.logger.bind(tag=TAG).info("结束对话，无需发送结束提示语")
                await conn.close()
                return
            prompt = end_prompt.get("prompt")
            if not prompt:
                prompt = "请你以```时间过得真快```未来头，用富有感情、依依不舍的话来结束这场对话吧。！"
            await startToChat(conn, prompt)


async def max_out_size(conn: "ConnectionHandler"):
    # 播放超出最大输出字数的提示
    conn.client_abort = False
    text = "不好意思，我现在有点事情要忙，明天这个时候我们再聊，约好了哦！明天不见不散，拜拜！"
    await send_stt_message(conn, text)
    file_path = "config/assets/max_output_size.wav"
    opus_packets = await audio_to_data(file_path)
    conn.tts.tts_audio_queue.put((SentenceType.LAST, opus_packets, text))
    conn.close_after_chat = True


async def check_bind_device(conn: "ConnectionHandler"):
    if conn.bind_code:
        # 确保bind_code是6位数字
        if len(conn.bind_code) != 6:
            conn.logger.bind(tag=TAG).error(f"无效的绑定码格式: {conn.bind_code}")
            text = "绑定码格式错误，请检查配置。"
            await send_stt_message(conn, text)
            return

        text = f"请登录控制面板，输入{conn.bind_code}，绑定设备。"
        await send_stt_message(conn, text)

        # 播放提示音
        music_path = "config/assets/bind_code.wav"
        opus_packets = await audio_to_data(music_path)
        conn.tts.tts_audio_queue.put((SentenceType.FIRST, opus_packets, text))

        # 逐个播放数字
        for i in range(6):  # 确保只播放6位数字
            try:
                digit = conn.bind_code[i]
                num_path = f"config/assets/bind_code/{digit}.wav"
                num_packets = await audio_to_data(num_path)
                conn.tts.tts_audio_queue.put((SentenceType.MIDDLE, num_packets, None))
            except Exception as e:
                conn.logger.bind(tag=TAG).error(f"播放数字音频失败: {e}")
                continue
        conn.tts.tts_audio_queue.put((SentenceType.LAST, [], None))
    else:
        # 播放未绑定提示
        conn.client_abort = False
        text = f"没有找到该设备的版本信息，请正确配置 OTA地址，然后重新编译固件。"
        await send_stt_message(conn, text)
        music_path = "config/assets/bind_not_found.wav"
        opus_packets = await audio_to_data(music_path)
        conn.tts.tts_audio_queue.put((SentenceType.LAST, opus_packets, text))

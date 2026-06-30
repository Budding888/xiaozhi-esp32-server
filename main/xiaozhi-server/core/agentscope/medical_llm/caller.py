"""
MedicalQwen LLM 调用模块

从 search_medical_question.py 抽取的 MedicalQwen 调用相关函数。
包含流式/非流式调用、TTS流式输出等功能。
"""

from typing import Optional, TYPE_CHECKING

from core.agentscope.config.medical_config import (
    _get_medical_config,
    _medical_verify,
    medical_system_prompt,
    medical_system_prompt_v2,
)
from config.logger import setup_logging

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()


def _call_medical_qwen(conn: "ConnectionHandler", question: str, knowledge_context: str) -> Optional[str]:
    """
    调用医疗Qwen LLM进行推理（流式，带TTS输出）

    Args:
        conn: 连接处理器
        question: 患者问题
        knowledge_context: RAGFlow检索的知识库内容

    Returns:
        str: 医疗Qwen生成的回答文本，失败时返回None
    """
    from core.utils import llm as llm_utils
    from core.providers.tts.dto.dto import ContentType, TTSMessageDTO, SentenceType

    medical_config = _get_medical_config(conn)
    if not medical_config:
        logger.bind(tag=TAG).error("未找到 MedicalQwen 配置")
        return None
    logger.bind(tag=TAG).info(
        f"调用 MedicalQwen: {medical_config.get('base_url')}"
    )

    try:
        medical_llm = llm_utils.create_instance("medical_qwen", medical_config)
    except Exception as e:
        logger.bind(tag=TAG).error(f"创建 MedicalQwen 实例失败: {e}")
        return None

    if knowledge_context:
        user_prompt = f"""【知识库参考内容】
        {knowledge_context}

        【患者问题】
        {question}

        回答要求：
        1. 逐条覆盖以上参考内容中的每一个要点，全部保留、不得遗漏；
        2. 用连贯的段落回答，确保每个要点都被自然提及；
        3. 全部要点覆盖完后，如果知识库不足以完全回答问题，补充你的医学知识；
        4. 如果知识库已完整覆盖，则无需补充；
        5. 回答完整通顺，无残缺短句；"""
    else:
        user_prompt = f"""【患者问题】 {question} 回答结束后，另起一行输出 ----本次回答完成回答完成----"""

    try:
        dialogue = [
            {"role": "system", "content": medical_system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        full_answer = ""
        for chunk in medical_llm.response("", dialogue):
            if not chunk:
                continue
            full_answer += chunk
            # 流式输出到 TTS
            try:
                conn.tts.tts_text_queue.put(
                    TTSMessageDTO(
                        sentence_id=conn.sentence_id,
                        sentence_type=SentenceType.MIDDLE,
                        content_type=ContentType.TEXT,
                        content_detail=chunk,
                    )
                )
            except Exception:
                pass

        if full_answer:
            verified = _medical_verify(full_answer.strip(), conn)
            return verified
        logger.bind(tag=TAG).warning("MedicalQwen 返回空内容")
        return None
    except Exception as e:
        logger.bind(tag=TAG).error(f"MedicalQwen 调用失败: {e}")
        return None


def _call_medical_qwen_v2(conn: "ConnectionHandler", question: str) -> Optional[str]:
    """
    调用医疗Qwen LLM进行推理（流式，仅患者问题，不投喂知识库）

    Args:
        conn: 连接处理器
        question: 患者问题

    Returns:
        str: 回答文本，失败时返回None
    """
    from core.utils import llm as llm_utils
    from core.providers.tts.dto.dto import ContentType, TTSMessageDTO, SentenceType

    medical_config = _get_medical_config(conn)
    if not medical_config:
        return None

    try:
        medical_llm = llm_utils.create_instance("medical_qwen", medical_config)
    except Exception as e:
        logger.bind(tag=TAG).error(f"创建 MedicalQwen 实例失败: {e}")
        return None

    try:
        dialogue = [
            {"role": "system", "content": medical_system_prompt_v2},
            {"role": "user", "content": f"【患者问题】{question}"},
        ]

        full_answer = ""
        for chunk in medical_llm.response("", dialogue):
            if not chunk:
                continue
            full_answer += chunk
            try:
                conn.tts.tts_text_queue.put(
                    TTSMessageDTO(
                        sentence_id=conn.sentence_id,
                        sentence_type=SentenceType.MIDDLE,
                        content_type=ContentType.TEXT,
                        content_detail=chunk,
                    )
                )
            except Exception:
                pass

        if full_answer:
            return _medical_verify(full_answer.strip(), conn)
        return None
    except Exception as e:
        logger.bind(tag=TAG).error(f"MedicalQwen v2 调用失败: {e}")
        return None


def _call_medical_qwen_v2_no_stream(conn: "ConnectionHandler", question: str) -> Optional[str]:
    """
    调用医疗Qwen LLM进行推理（非流式，供并行调用）

    Args:
        conn: 连接处理器
        question: 患者问题

    Returns:
        str: 回答文本，失败时返回None
    """
    from core.utils import llm as llm_utils

    medical_config = _get_medical_config(conn)
    if not medical_config:
        logger.bind(tag=TAG).error("未找到 MedicalQwen 配置")
        return None

    try:
        medical_llm = llm_utils.create_instance("medical_qwen", medical_config)
    except Exception as e:
        logger.bind(tag=TAG).error(f"创建 MedicalQwen 实例失败: {e}")
        return None

    try:
        full_answer = medical_llm.response_no_stream(
            system_prompt=medical_system_prompt_v2,
            user_prompt=f"【患者问题】{question}",
        )

        if full_answer and len(full_answer.strip()) >= 5:
            verified = _medical_verify(full_answer.strip(), conn)
            logger.bind(tag=TAG).info(
                f"MedicalQwen v2 no_stream 完成，长度: {len(verified)} 字符"
            )
            return verified
        logger.bind(tag=TAG).warning("MedicalQwen v2 no_stream 返回空或过短")
        return None
    except Exception as e:
        logger.bind(tag=TAG).error(
            f"MedicalQwen v2 no_stream 失败: {type(e).__name__}: {e}"
        )
        return None

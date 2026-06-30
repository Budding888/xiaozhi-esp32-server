"""
RAGFlow 知识库检索模块

从 search_medical_question.py 抽取的 RAGFlow 检索相关函数。
包含 Query 改写、知识库检索、知识压缩等功能。
"""

from typing import Optional, TYPE_CHECKING

from core.agentscope.config.medical_config import (
    query_system_prompt,
    _strip_ragflow_markdown,
    strip_end_punctuation,
)
from config.logger import setup_logging

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()


def _send_progress_tts(conn, text: str):
    """向TTS队列发送进度提示文本"""
    try:
        from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=conn.sentence_id,
                sentence_type=SentenceType.MIDDLE,
                content_type=ContentType.TEXT,
                content_detail=text,
            )
        )
    except Exception:
        pass


def _optimize_rag_query(conn: "ConnectionHandler", question: str) -> str:
    """
    Rag检索词优化改写：将口语化问题改写为知识库检索友好的关键词形式

    Args:
        conn: 连接处理器
        question: 患者提出的原始问题

    Returns:
        str: 改写后的检索query，失败返回空字符串
    """
    query_user_input = f"患者问题：{question}\n优化后的查询："
    try:
        optimized = conn.llm.response_no_stream(
            system_prompt=query_system_prompt,
            user_prompt=query_user_input,
            temperature=0.2,
            max_tokens=128,
        )
        logger.bind(tag=TAG).info(
            f"Query改写 | 原始:「{question}」→ 模型输出:「{optimized}」"
        )

        if not optimized:
            logger.bind(tag=TAG).warning("Query改写 | 模型返回为空，降级原始问题")
            return ""

        # ===== 清洗流水线 =====
        optimized = optimized.strip().strip('"').strip("'")
        optimized = " ".join(optimized.splitlines())
        for sep in ["，", "、", ";", "；"]:
            optimized = optimized.replace(sep, " ")
        optimized = strip_end_punctuation(optimized)
        optimized = " ".join(optimized.split())
        logger.bind(tag=TAG).info(
            f"Query改写 | 清洗后:「{optimized}」(len={len(optimized)})"
        )

        # ===== 校验流水线 =====
        if len(optimized) < 4:
            logger.bind(tag=TAG).warning(
                f"Query改写 | 结果过短({len(optimized)}): '{optimized}'，降级原始问题"
            )
            return ""
        if len(optimized) > 50:
            logger.bind(tag=TAG).warning(
                f"Query改写 | 结果过长({len(optimized)}字符)，降级原始问题"
            )
            return ""
        sentence_markers = ["。", "？", "！", "："]
        if any(marker in optimized for marker in sentence_markers):
            logger.bind(tag=TAG).warning(
                f"Query改写 | 含句子标点，降级原始问题。片段: {optimized[:120]}"
            )
            return ""
        return optimized
    except Exception as e:
        logger.bind(tag=TAG).error(f"Query改写 | 调用失败: {e}")
        return ""


def _query_knowledge_base(conn: "ConnectionHandler", question: str) -> str:
    """
    查询RAGFlow知识库（含Query改写优化）

    Args:
        conn: 连接处理器
        question: 查询问题

    Returns:
        str: 知识库检索结果文本，为空时表示无结果
    """
    try:
        optimized_query = _optimize_rag_query(conn, question)
        search_query = optimized_query or question
        if optimized_query:
            logger.bind(tag=TAG).info(
                f"Query改写成功: 「{question}」→「{optimized_query}」"
            )
        else:
            logger.bind(tag=TAG).info(
                f"Query改写未生效，使用原始问题检索: 「{question}」"
            )

        from plugins_func.functions.search_from_ragflow import search_from_ragflow_v2
        from plugins_func.register import Action

        rag_result = search_from_ragflow_v2(conn, question=search_query)

        if rag_result.action == Action.REQLLM and rag_result.result:
            raw_text = rag_result.result.strip()
            knowledge_text = _strip_ragflow_markdown(raw_text)
            logger.bind(tag=TAG).info(
                f"RAGFlow返回内容长度: {len(knowledge_text)} 字符"
            )

            # 用通用LLM压缩
            compressed = _compress_knowledge(conn, question, knowledge_text)
            if compressed and compressed != knowledge_text:
                ratio = len(compressed) / len(knowledge_text) * 100
                logger.bind(tag=TAG).info(
                    f"知识库压缩完成: {len(knowledge_text)}→{len(compressed)} 字符 ({ratio:.0f}%)"
                )
                return compressed
            return knowledge_text
        logger.bind(tag=TAG).warning("RAGFlow未返回有效结果")
    except Exception as e:
        logger.bind(tag=TAG).error(f"RAGFlow查询失败: {e}")

    return ""


def _compress_knowledge(conn: "ConnectionHandler", question: str, knowledge_text: str) -> str:
    """
    用通用LLM压缩知识库内容

    Args:
        conn: 连接处理器
        question: 患者原始问题
        knowledge_text: 原始知识库文本

    Returns:
        str: 压缩后的知识摘要，空字符串表示不压缩
    """
    if not knowledge_text or len(knowledge_text) < 300:
        return ""

    system_prompt = "你是一个医学知识整理助手。请将以下知识库内容压缩为简洁的摘要。"
    user_prompt = (
        f"要求：\n"
        f"1. 只保留与用户问题直接相关的信息\n"
        f"2. 合并重复和相似的内容\n"
        f"3. 按逻辑顺序整理\n"
        f"4. 去除模糊和不确定的表述\n"
        f"5. 输出简洁连贯的段落，控制在800字以内\n\n"
        f"用户问题：{question}\n\n"
        f"知识库内容：\n{knowledge_text}\n\n"
    )

    _send_progress_tts(conn, "知识库查询结果整理中。")

    try:
        compressed = conn.llm.response_no_stream(system_prompt, user_prompt)
        if compressed:
            cleaned = compressed.strip()
            if len(cleaned) >= 30:
                logger.bind(tag=TAG).info(
                    f"知识库压缩成功: {len(knowledge_text)}→{len(cleaned)} 字符"
                )
                return cleaned
            logger.bind(tag=TAG).warning(
                f"知识库压缩结果过短({len(cleaned)}字符)，使用原始内容"
            )
        else:
            logger.bind(tag=TAG).warning("知识库压缩返回空，使用原始内容")
    except Exception as e:
        logger.bind(tag=TAG).error(f"知识库压缩失败: {e}")

    return ""


def _parallel_rag_search(conn: "ConnectionHandler", question: str) -> Optional[str]:
    """
    供并行路径调用的知识库检索（不压缩，避免子线程访问通用LLM）

    Args:
        conn: 连接处理器
        question: 改写后的检索query

    Returns:
        str: 清理后的知识库文本，失败返回None
    """
    try:
        from plugins_func.functions.search_from_ragflow import search_from_ragflow_v2
        from plugins_func.register import Action

        rag_result = search_from_ragflow_v2(conn, question=question)
        if rag_result and rag_result.action == Action.REQLLM and rag_result.result:
            raw_text = rag_result.result.strip()
            knowledge_text = _strip_ragflow_markdown(raw_text)
            if knowledge_text:
                logger.bind(tag=TAG).info(
                    f"并行Rag检索完成，长度: {len(knowledge_text)} 字符"
                )
                return knowledge_text
    except Exception as e:
        logger.bind(tag=TAG).error(f"并行知识库检索失败: {e}")
    return None

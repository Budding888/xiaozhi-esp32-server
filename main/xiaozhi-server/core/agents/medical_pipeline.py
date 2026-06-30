"""
AgentScope 版医疗问答管道

基于 AgentScope 编排框架，封装现有 V2 并行流核心函数。
保留所有现有业务逻辑，仅改变编排方式。

设计原则:
1. 不重写现有函数: 直接调用 search_medical_question.py 中的已有函数
2. 异常安全: 任何阶段失败自动降级
3. 可切换: 通过 agent_mode 控制走 agentscope 还是 legacy 路径

用法:
    from core.agents.medical_pipeline import agentscope_medical_flow
    answer = await agentscope_medical_flow(conn, "我血压高吃什么")
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


def _send_progress_tts(conn, text: str):
    """向 TTS 队列发送进度提示文本"""
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


def agentscope_medical_flow(conn, question: str) -> str:
    """
    AgentScope 版医疗问答管道（主入口）

    编排流程（与 V2 并行流功能等价）：
    1. Query 改写 → 2. RAG + MedicalQwen 并行检索 → 3. 融合 → 4. 校验

    参数:
        conn: ConnectionHandler 实例
        question: 患者问题

    返回:
        str: 回答文本（已校验），None 表示处理失败
    """
    import re

    if not question:
        logger.bind(tag=TAG).warning("============agentscope_medical_flow: 问题为空============")
        return None

    logger.bind(tag=TAG).info(
        f"============[AgentScope] 医疗管道启动, question={question[:80]}============"
    )

    # ──────────────────────────────────────────────
    # Stage 0: 进度播报 + RAGFlow 健康检查
    # ──────────────────────────────────────────────
    clean_question = re.sub(r'[^一-鿿A-Za-z0-9]', '', question).strip() or question
    _send_progress_tts(conn, "好的。正在为您查询，请耐心等待。")

    # RAGFlow 健康检查
    ragflow_healthy = False
    try:
        from plugins_func.functions.search_from_ragflow import ragflow_health_check
        ragflow_healthy = ragflow_health_check(conn)
        logger.bind(tag=TAG).info(
            f"============[AgentScope] RAGFlow健康检查: {'✅' if ragflow_healthy else '❌'}============"
        )
    except Exception as e:
        logger.bind(tag=TAG).warning(f"============[AgentScope] RAGFlow健康检查失败: {e}============")

    # ──────────────────────────────────────────────
    # Stage 1: Query 改写（顺序执行）
    # ──────────────────────────────────────────────
    _send_progress_tts(conn, "正在检索知识库。")

    try:
        from core.agentscope.rag.search import _optimize_rag_query
        optimized_query = _optimize_rag_query(conn, question)
    except Exception as e:
        logger.bind(tag=TAG).warning(f"============[AgentScope] Query改写失败: {e}============")
        optimized_query = None

    search_query = optimized_query or question
    logger.bind(tag=TAG).info(
        f"============[AgentScope] Query改写: 「{question}」→「{search_query}」============"
    )

    # ──────────────────────────────────────────────
    # Stage 2: 并行检索（RAGFlow + MedicalQwen）
    # ──────────────────────────────────────────────
    rag_result = None
    medical_result = None

    if ragflow_healthy:
        # RAGFlow + MedicalQwen 并行执行
        _send_progress_tts(conn, "正在检索知识库和大模型。")

        with ThreadPoolExecutor(max_workers=2) as executor:
            # 线程 A: RAGFlow 检索
            future_rag = executor.submit(
                _parallel_rag_search, conn, search_query
            )
            # 线程 B: MedicalQwen 推理
            future_medical = executor.submit(
                _parallel_medical_search, conn, question
            )

            # 等待线程 A 完成
            try:
                rag_result = future_rag.result(timeout=15)
                if rag_result:
                    logger.bind(tag=TAG).info(f"============[AgentScope] RAGFlow完成, 长度:{len(rag_result)}字符============")
            except Exception as e:
                logger.bind(tag=TAG).error(f"============[AgentScope] RAGFlow并行失败: {e}============")

            # 等待线程 B 完成
            try:
                medical_result = future_medical.result(timeout=20)
                if medical_result:
                    logger.bind(tag=TAG).info(
                        f"============[AgentScope] MedicalQwen完成, 长度:{len(medical_result)}字符============"
                    )
            except Exception as e:
                logger.bind(tag=TAG).error(
                    f"============[AgentScope] MedicalQwen并行失败: {e}============"
                )
    else:
        # RAGFlow 不可用，仅执行 MedicalQwen
        _send_progress_tts(conn, "正在检索大模型。")
        medical_result = _parallel_medical_search(conn, question)

    # ──────────────────────────────────────────────
    # Stage 3: 融合（合并 RAG + MedicalQwen 结果）
    # ──────────────────────────────────────────────
    _send_progress_tts(conn, "正在为您整理结果。")

    if rag_result and medical_result:
        # 两条结果都有，融合
        merged = _merge_results(conn, question, rag_result, medical_result)
    elif medical_result:
        # 仅有医疗推理结果
        merged = medical_result
        logger.bind(tag=TAG).info("============[AgentScope] 仅MedicalQwen结果============")
    elif rag_result:
        # 仅有知识库结果
        merged = rag_result
        logger.bind(tag=TAG).info("============[AgentScope] 仅知识库结果============")
    else:
        logger.bind(tag=TAG).warning("============[AgentScope] 所有检索无结果============")
        return None

    # ──────────────────────────────────────────────
    # Stage 4: 内容安全校验
    # ──────────────────────────────────────────────
    try:
        from core.agentscope.config.medical_config import _medical_verify
        merged = _medical_verify(merged)
    except Exception as e:
        logger.bind(tag=TAG).error(f"============[AgentScope] 内容校验失败: {e}============")

    logger.bind(tag=TAG).info(
        f"============[AgentScope] 医疗管道完成, 回答长度:{len(merged)}字符============"
    )
    return merged


def _parallel_rag_search(conn, question: str) -> str:
    """
    并行 RAGFlow 检索（供线程池调用）。

    与 V2 并行流中的 _parallel_rag_search 等价。
    """
    try:
        from plugins_func.functions.search_from_ragflow import (
            search_from_ragflow_v2,
        )
        from plugins_func.functions.search_medical_question import (
            _strip_ragflow_markdown,
        )

        rag_result = search_from_ragflow_v2(conn, question=question)
        if rag_result and hasattr(rag_result, "action"):
            raw_text = (rag_result.result or "").strip()
            if raw_text:
                return _strip_ragflow_markdown(raw_text)
    except Exception as e:
        logger.bind(tag=TAG).error(f"============[AgentScope] RAGFlow检索失败: {e}============")
    return None


def _parallel_medical_search(conn, question: str) -> str:
    """
    并行 MedicalQwen 推理（供线程池调用，非流式）。

    与 V2 并行流中的 _call_medical_qwen_v2_no_stream 等价。
    """
    try:
        from core.agentscope.config.medical_config import (
            _get_medical_config,
            _medical_verify,
        )
        from core.utils import llm as llm_utils

        medical_config = _get_medical_config(conn)
        if not medical_config:
            logger.bind(tag=TAG).warning("============[AgentScope] MedicalQwen未配置============")
            return None

        medical_llm = llm_utils.create_instance("medical_qwen", medical_config)
        if not medical_llm:
            return None

        # 使用 V2 system prompt
        from core.agentscope.config.medical_config import (
            medical_system_prompt_v2,
        )

        full_answer = medical_llm.response_no_stream(
            system_prompt=medical_system_prompt_v2,
            user_prompt=f"【患者问题】{question}",
        )

        if full_answer and len(full_answer.strip()) >= 5:
            verified = _medical_verify(full_answer.strip())
            return verified
    except Exception as e:
        logger.bind(tag=TAG).error(
            f"============[AgentScope] MedicalQwen调用失败: {type(e).__name__}: {e}============"
        )
    return None


def _merge_results(conn, question: str, kb_text: str, medical_text: str) -> str:
    """
    用通用LLM融合知识库和医疗推理结果（流式版）。

    当两条结果都存在时，调用 _merge_rag_and_medical_streaming 实现流式融合，
    每生成一句立即送 TTS 播报（不等全部生成完）。
    同时设置 conn._streaming_tts_done 标记，通知调用方跳过重复 TTS。

    单一结果时直接返回（非流式），调用方自行处理 TTS。
    """
    # 只有一条结果时直接返回
    if not kb_text:
        return medical_text
    if not medical_text:
        return kb_text

    try:
        from core.agentscope.fusion.fuser import (
            _merge_rag_and_medical_streaming,
        )
        merged = _merge_rag_and_medical_streaming(conn, question, kb_text, medical_text)
        if merged:
            # 标记 TTS 已在流式融合内部完成，通知 _agentscope_chat 跳过重复 TTS
            conn._streaming_tts_done = True
            logger.bind(tag=TAG).info(
                f"============[AgentScope] 流式融合完成, 长度:{len(merged)}字符============"
            )
            return merged
    except Exception as e:
        logger.bind(tag=TAG).error(
            f"============[AgentScope] 流式融合失败: {e}, 降级到第一条结果============"
        )

    # 融合失败，返回知识库结果（通常更可靠）
    return kb_text

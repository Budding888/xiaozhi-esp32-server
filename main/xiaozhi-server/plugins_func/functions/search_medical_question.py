"""
医疗问答插件

由通用LLM的function_call触发，编排完整医疗问答流程：
RAGFlow知识库检索 → 医疗Qwen推理 → 内容安全校验 → 返回给通用LLM润色

核心函数已抽取到以下子模块（可独立测试）：
- core/agentscope/config/medical_config.py      — 常量、prompts、配置读取
- core/agentscope/config/medical_keywords.py    — 医疗关键词
- core/agentscope/rag/search.py                 — 知识库检索
- core/agentscope/medical_llm/caller.py         — MedicalQwen调用
- core/agentscope/fusion/fuser.py               — 结果融合

依赖：
- RAGFlow知识库：通过 search_from_ragflow 插件查询（Docker运行）
- 医疗Qwen LLM：外部项目部署的 Qwen3.5-4B-Medical
- 通用LLM：通过项目现有的 function_call 意图识别触发本插件
"""

from plugins_func.register import register_function, ToolType, ActionResponse, Action
from plugins_func.functions.search_from_ragflow import search_from_ragflow_v2, ragflow_health_check
from config.logger import setup_logging
from typing import TYPE_CHECKING

# 从抽取的子模块导入（避免重复定义）
from core.agentscope.config.medical_config import (
    MEDICAL_QA_FUNCTION_DESC,
    medical_system_prompt,
    medical_system_prompt_v2,
    _get_medical_config,
    _get_disclaimer_text,
    _strip_ragflow_markdown,
    _medical_verify,
)
from core.agentscope.rag.search import (
    _optimize_rag_query,
    _parallel_rag_search,
    _query_knowledge_base,
)
from core.agentscope.medical_llm.caller import (
    _call_medical_qwen,
    _call_medical_qwen_v2_no_stream,
)
from core.agentscope.fusion.fuser import (
    _merge_rag_and_medical,
    _merge_rag_and_medical_streaming,
    STREAMING_DONE_MARKER,
)

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()


def _send_progress_tts(conn, text: str):
    """向TTS队列发送进度提示文本，让用户实时了解处理进度"""
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


@register_function("search_medical_question", MEDICAL_QA_FUNCTION_DESC, ToolType.SYSTEM_CTL)
def search_medical_question(conn: "ConnectionHandler", question=None):
    """
    医疗问答入口 — 被通用LLM的function_call触发

    流程:
        0. 健康检查（决定走正常流水线还是降级路径）
        1. 正常：Query改写 → RAGFlow检索 → MedicalQwen推理 → 校验 → 通用LLM润色
        2. 降级：RAGFlow检索 → 通用LLM回答（基于知识库或自身知识）

    Args:
        conn: 连接处理器，包含当前对话的配置和状态
        question: 患者提出的医疗问题原文

    Returns:
        ActionResponse: 正常返回REQLLM，降级返回RESPONSE
    """
    if not question:
        return ActionResponse(Action.RESPONSE, None, "请告诉我您的问题")

    logger.bind(tag=TAG).info(f"===========触发腹透患者医疗问答(search_medical_question)===========，问题: {question}")

    # ===== 阶段0：健康检查 =====
    medical_config = _get_medical_config()
    logger.bind(tag=TAG).info(f"===========MedicalQwen配置参数medical_config===========: {medical_config}")
    if medical_config:
        from core.providers.llm.medical_qwen.medical_qwen import LLMProvider
        qwen_healthy = LLMProvider.health_check(medical_config)
        logger.bind(tag=TAG).info(f"===========MedicalQwen 健康检查结果: {'【正常】' if qwen_healthy else '【不可用，进入降级路径】==========='}")
    else:
        qwen_healthy = False
        logger.bind(tag=TAG).warning("===========MedicalQwen未配置，【进入降级路径】===========")

    if qwen_healthy:
        return _medical_search_flow_v2(conn, question)
    else:
        return _fallback_medical_flow(conn, question)


def _medical_search_flow(conn, question):
    """
    集成医疗大模型方案2: 正常医疗问答流水线（MedicalQwen 健康时走此路径）

    流程：Query改写 → RAGFlow检索 → 知识压缩 → MedicalQwen推理 → 校验
    """
    import re

    clean_question = re.sub(r'[^一-鿿A-Za-z0-9]', '', question).strip() or question
    _send_progress_tts(conn, "好的。")
    _send_progress_tts(conn, "欢迎使用小讷音箱，很高兴为您服务。")
    _send_progress_tts(conn, f"正在为您查询关于{clean_question}，请稍候。")

    _send_progress_tts(conn, "正在检索知识库。")
    knowledge_context = _query_knowledge_base(conn, question)
    logger.bind(tag=TAG).info(f"===========RAGFlow检索结果【整理之后的】===========: {knowledge_context}")

    _send_progress_tts(conn, "已为您查询到以下医疗信息。")
    medical_answer = _call_medical_qwen(conn, question, knowledge_context)
    logger.bind(tag=TAG).info(f"===========医疗大模型回答结果===========：{medical_answer}")
    if not medical_answer:
        return ActionResponse(Action.RESPONSE, None, "医疗系统繁忙，请稍后再试")

    logger.bind(tag=TAG).info(f"===========医疗问答完成，回答长度: {len(medical_answer)} 字符===========")
    return ActionResponse(Action.REQLLM, medical_answer, None)


def _medical_search_flow_v2(conn, question):
    """
    集成医疗大模型方案3: 正常医疗问答流水线 V2（知识库检索与医疗大模型推理异步并行）

    流程：
      Query改写 ─┬─→ 线程A: RAGFlow检索 ──┐
                 │                         ├─→ 通用LLM融合 ─→ 校验 ─→ REQLLM
                 └─→ 线程B: MedicalQwen ───┘

    耗时对比：
      V1（串行）: Query改写 + RAGFlow + 压缩 + MedicalQwen = ~78s
      V2（并行）: Query改写 + max(RAGFlow, MedicalQwen) + 融合 = ~48s
    """
    import re
    from concurrent.futures import ThreadPoolExecutor

    clean_question = re.sub(r'[^一-鿿A-Za-z0-9]', '', question).strip() or question
    _send_progress_tts(conn, "好的。")
    _send_progress_tts(conn, "欢迎使用小讷音箱，很高兴为您服务。")
    _send_progress_tts(conn, f"正在为您查询关于{clean_question}，结果尽快为您呈现，请耐心等待。")

    # ===== 阶段1：Query改写（顺序执行，快速）=====
    _send_progress_tts(conn, "开始进行知识库和大模型检索。")
    optimized_query = _optimize_rag_query(conn, question)
    search_query = optimized_query or question
    logger.bind(tag=TAG).info(f"===========用户query改写结果===========：{search_query}")

    # ===== 阶段2：RAGFlow 健康检查 =====
    ragflow_healthy = ragflow_health_check(conn)
    logger.bind(tag=TAG).info(f"===========RAGFlow 健康检查结果: {'【正常】' if ragflow_healthy else '【不可用】，跳过知识库检索'}===========")

    rag_result = None
    medical_result = None

    if ragflow_healthy:
        with ThreadPoolExecutor(max_workers=2) as executor:
            _send_progress_tts(conn, "正在检索知识库。")
            future_rag = executor.submit(_parallel_rag_search, conn, search_query)

            _send_progress_tts(conn, "正在检索大模型。")
            future_medical = executor.submit(_call_medical_qwen_v2_no_stream, conn, question)

        try:
            rag_result = future_rag.result()
            if rag_result:
                logger.bind(tag=TAG).info(f"===========【RAGFlow】并行检索结果===========：{rag_result}")
        except Exception as e:
            logger.bind(tag=TAG).error(f"===========并行RAGFlow失败===========: {e}")

        try:
            medical_result = future_medical.result()
            if medical_result:
                logger.bind(tag=TAG).info(f"===========【MedicalQwen】并行检索结果===========：{medical_result}")
        except Exception as e:
            logger.bind(tag=TAG).error(f"===========并行MedicalQwen失败===========: {e}")
    else:
        logger.bind(tag=TAG).info("RAGFlow 不可用，仅执行 MedicalQwen 推理")
        _send_progress_tts(conn, "正在检索大模型。")
        medical_result = _call_medical_qwen_v2_no_stream(conn, question)
        if medical_result:
            logger.bind(tag=TAG).info(f"===========【MedicalQwen】单独检索结果===========：{medical_result}")

    # ===== 阶段3：通用LLM融合（流式：生成一句播报一句） =====
    _send_progress_tts(conn, "正在为您整理相关检索结果，麻烦您稍等片刻哦。")

    merged_answer = _merge_rag_and_medical_streaming(
        conn, question, rag_result, medical_result
    )

    if merged_answer:
        logger.bind(tag=TAG).info(
            f"===========流式融合完成，长度: {len(merged_answer)} 字符==========="
        )
        # 使用 STREAMING_DONE_MARKER 标记 TTS 已在流式融合内部完成
        return ActionResponse(
            Action.RESPONSE, merged_answer, STREAMING_DONE_MARKER
        )

    if medical_result:
        logger.bind(tag=TAG).warning("融合失败，降级使用MedicalQwen结果")
        return ActionResponse(Action.REQLLM, medical_result, None)

    if rag_result:
        logger.bind(tag=TAG).warning("融合失败，降级使用知识库结果")
        return ActionResponse(Action.REQLLM, rag_result, None)

    return ActionResponse(Action.RESPONSE, None, "医疗系统繁忙，请稍后再试")


def _fallback_medical_flow(conn, question):
    """
    降级医疗问答（MedicalQwen 不可用时走此路径）

    直接查 RAGFlow，然后用通用LLM回答：
    - Level 1：RAGFlow有结果 → 通用LLM 基于知识库整理回答
    - Level 2：RAGFlow无结果 → 通用LLM 基于自身知识回答
    - Level 3：通用LLM也失败 → 错误消息
    """
    import re

    logger.bind(tag=TAG).warning(f"===========进入【医疗降级路径】===========，问题: {question}")

    clean_question = re.sub(r'[^一-鿿A-Za-z0-9]', '', question).strip() or question
    _send_progress_tts(conn, "好的。")
    _send_progress_tts(conn, f"正在查询关于{clean_question}的问题，请稍候。")
    _send_progress_tts(conn, "正在检索知识库。")

    try:
        rag_result = search_from_ragflow_v2(conn, question=question)

        if rag_result and rag_result.action == Action.REQLLM and rag_result.result:
            knowledge_text = _strip_ragflow_markdown(rag_result.result.strip())
            if knowledge_text:
                logger.bind(tag=TAG).info(f"============【降级路径：RAGFlow】 返回内容如下:============\n {knowledge_text}")
                _send_progress_tts(conn, "已查询到相关知识，正在整理回答。")
                fallback_answer = _fallback_answer_with_llm_streaming(conn, question, knowledge_text)
                if fallback_answer:
                    fallback_answer = _medical_verify(fallback_answer)
                    return ActionResponse(Action.RESPONSE, fallback_answer, STREAMING_DONE_MARKER)
    except Exception as e:
        logger.bind(tag=TAG).error(f"============【降级路径：RAGFlow】 查询失败: {e}")

    logger.bind(tag=TAG).info("============【降级路径：RAGFlow】 无结果，使用通用LLM自身知识============")
    _send_progress_tts(conn, "正在为您解答，请稍候。")
    fallback_answer = _fallback_answer_with_llm_streaming(conn, question, None)
    if fallback_answer:
        fallback_answer = _medical_verify(fallback_answer)
        return ActionResponse(Action.RESPONSE, fallback_answer, STREAMING_DONE_MARKER)

    logger.bind(tag=TAG).error("============降级路径全部失败============")
    return ActionResponse(Action.RESPONSE, None, "医疗系统繁忙，请稍后再试")


def _fallback_answer_with_llm(conn, question, knowledge_text):
    """
    用通用LLM回答医疗问题（降级路径）
    非流式版：必须等待通用LLM整段返回结果之后，方可逐句生成播报语句

    Args:
        conn: 连接处理器
        question: 患者问题
        knowledge_text: 知识库结果（可能为None）

    Returns:
        str: 通用LLM生成的回答，失败时返回None
    """
    system_prompt = (
        "你是一名专业的医疗健康助手。请用简洁易懂的中文回答患者问题，确保信息准确。"
        "注意：如果无法确定，请明确建议患者咨询医生，不要猜测。"
    )

    if knowledge_text:
        user_prompt = (
            f"患者问题：{question}\n\n"
            f"参考信息：{knowledge_text}\n\n"
            f"请优先基于以上参考信息回答患者问题。如果参考信息不足以完整回答，"
            f"可以用你的医学知识补充。"
        )
    else:
        user_prompt = (
            f"患者问题：{question}\n\n"
            f"请根据你的医学知识回答患者问题。如果不确定，请建议就医。"
        )

    try:
        answer = conn.llm.response_no_stream(system_prompt, user_prompt)
        if answer and len(answer.strip()) >= 10:
            cleaned = answer.strip()
            logger.bind(tag=TAG).info(f"============【降级路径：通用LLM】回答成功: {cleaned}")
            return cleaned
        logger.bind(tag=TAG).warning("============【降级路径：通用LLM】返回空内容============")
    except Exception as e:
        logger.bind(tag=TAG).error(f"============降级路径通用LLM调用失败: {e}")

    return None


def _fallback_answer_with_llm_streaming(conn, question, knowledge_text):
    """
    流式版：用通用LLM回答医疗问题（降级路径），生成一句播报一句

    与 _fallback_answer_with_llm 功能相同，但使用 LLM 流式接口 response() 逐 token
    接收，每检测到一个完整句子立即调用 tts_one_sentence 播报。

    Args:
        conn: 连接处理器
        question: 患者问题
        knowledge_text: 知识库结果（可能为None）

    Returns:
        str: 通用LLM生成的全部文本，失败时返回None
    """
    from core.agentscope.fusion.fuser import _SENTENCE_END
    from core.providers.tts.dto.dto import ContentType

    system_prompt = (
        "你是一名专业的医疗健康助手。请用简洁易懂的中文回答患者问题，确保信息准确。"
        "注意：如果无法确定，请明确建议患者咨询医生，不要猜测。"
    )

    if knowledge_text:
        user_prompt = (
            f"患者问题：{question}\n\n"
            f"参考信息：{knowledge_text}\n\n"
            f"请优先基于以上参考信息回答患者问题。如果参考信息不足以完整回答，"
            f"可以用你的医学知识补充。"
        )
    else:
        user_prompt = (
            f"患者问题：{question}\n\n"
            f"请根据你的医学知识回答患者问题。如果不确定，请建议就医。"
        )

    dialogue = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    full_text = ""
    sentence_buf = ""

    try:
        logger.bind(tag=TAG).info("===========降级路径：通用LLM开始流式输出回答===========")
        for token in conn.llm.response("", dialogue):
            if not token:
                continue
            full_text += token
            sentence_buf += token

            if _SENTENCE_END.search(token) and len(sentence_buf.strip()) >= 3:
                clean = sentence_buf.strip()
                try:
                    conn.tts.tts_one_sentence(
                        conn, ContentType.TEXT, content_detail=clean
                    )
                except Exception as tts_err:
                    logger.bind(tag=TAG).warning(
                        f"============降级流式TTS推送失败: {tts_err}"
                    )
                sentence_buf = ""
    except Exception as e:
        logger.bind(tag=TAG).error(f"============降级流式LLM调用失败: {e}")
        if len(full_text.strip()) < 10:
            return None

    # 推送剩余文本
    remaining = sentence_buf.strip()
    if len(remaining) >= 3:
        try:
            conn.tts.tts_one_sentence(
                conn, ContentType.TEXT, content_detail=remaining
            )
        except Exception as tts_err:
            logger.bind(tag=TAG).warning(
                f"============降级流式推送剩余文本失败: {tts_err}"
            )

    full_text = full_text.strip()
    if len(full_text) >= 10:
        logger.bind(tag=TAG).info(
            f"============【降级流式】通用LLM回答成功, 长度:{len(full_text)}============"
        )
        return full_text

    logger.bind(tag=TAG).warning("============【降级流式】通用LLM返回空内容============")
    return None


def _send_disclaimer_tts(conn):
    """
    以独立 TTS 消息发送免责声明（带停顿，避免与主回答紧贴）
    """
    import time
    try:
        disclaimer = _get_disclaimer_text()
        time.sleep(1.0)
        from core.providers.tts.dto.dto import ContentType
        conn.tts.tts_one_sentence(
            conn, ContentType.TEXT, content_detail=f"⚠️ {disclaimer}"
        )
    except Exception:
        pass

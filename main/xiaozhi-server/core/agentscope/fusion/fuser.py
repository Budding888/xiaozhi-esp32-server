"""
医疗问答结果融合模块

从 search_medical_question.py 抽取的知识库 + MedicalQwen 结果融合函数。
"""

import re
from typing import Optional, TYPE_CHECKING

from config.logger import setup_logging

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()


def _merge_rag_and_medical(
    conn: "ConnectionHandler",
    question: str,
    kb_text: Optional[str],
    medical_text: Optional[str],
) -> Optional[str]:
    """
    用通用LLM融合知识库检索结果和医疗大模型推理结果

    Args:
        conn: 连接处理器
        question: 患者原始问题
        kb_text: 知识库检索结果（可能为空）
        medical_text: 医疗大模型推理结果（可能为空）

    Returns:
        str: 融合后的回答文本，失败时返回None
    """
    logger.bind(tag=TAG).info(f"融合知识库 + 医疗大模型: {question}")

    # 只有一条结果时直接返回
    if not kb_text:
        return medical_text
    if not medical_text:
        return kb_text

    system_prompt = (
        "你是腹透健康助手，融合两条信息源回答。\n"
        "要求：\n"
        "1. 以问题为中心，综合知识库和医疗模型的信息；\n"
        "2. 内容一致则合并，互补则综合，冲突以知识库为准；\n"
        "3. 分点回答（一. 二. 三.），口语表达；\n"
        "4. 使用简体中文输出，控制在600字以内。"
    )
    user_prompt = (
        f"【问题】{question}\n"
        f"【知识库】{kb_text}\n"
        f"【医疗模型】{medical_text}\n"
        f"融合以上信息回答患者问题。"
    )

    try:
        merged = conn.llm.response_no_stream(
            system_prompt,
            user_prompt,
            temperature=0.3,
            max_tokens=1024,
        )
        if merged and len(merged.strip()) > 20:
            return merged.strip()
        logger.bind(tag=TAG).warning("融合结果空或过短")
        return None
    except Exception as e:
        logger.bind(tag=TAG).error(f"融合失败: {e}")
        return None


# 中文句子结束标点
_SENTENCE_END = re.compile(r"[。！？!?]")

# 流式融合的 TTS 标记常量：外层通过检测此标记跳过重复 TTS 播报
STREAMING_DONE_MARKER = "__STREAMING_DONE__"


def _merge_rag_and_medical_streaming(
    conn: "ConnectionHandler",
    question: str,
    kb_text: Optional[str],
    medical_text: Optional[str],
) -> Optional[str]:
    """
    流式融合知识库 + MedicalQwen 结果（生成一句播报一句）

    与 `_merge_rag_and_medical` 功能相同，但使用 LLM 流式接口 response() 逐 token
    接收，每检测到一个完整的句子就立即调用 tts_one_sentence 播报，无需等全部生成完。

    收到的文本同时累积为 full_text，最终返回。

    返回约定的标记 `__STREAMING_DONE__` 给调用方，外层据此跳过重复 TTS 播报。
    对话记录使用 result 字段保存完整文本。

    注意：当仅有一条结果时（如 RAGFlow 不可用、仅 MedicalQwen 有输出），
    也会做 TTS 播报（非流式，单次 tts_one_sentence），因为调用方会携带
    STREAMING_DONE_MARKER 标记，依赖本函数完成 TTS 后告知外层跳过。
    """
    from core.providers.tts.dto.dto import ContentType

    logger.bind(tag=TAG).info(f"流式融合知识库 + 医疗大模型: {question}")

    # 只有一条结果时直接返回（但仍需做 TTS，因调用方会带 STREAMING_DONE_MARKER）
    if not kb_text and medical_text:
        try:
            conn.tts.tts_one_sentence(
                conn, ContentType.TEXT, content_detail=medical_text
            )
        except Exception as tts_err:
            logger.bind(tag=TAG).warning(f"流式融合单结果TTS失败: {tts_err}")
        return medical_text
    if not medical_text and kb_text:
        try:
            conn.tts.tts_one_sentence(
                conn, ContentType.TEXT, content_detail=kb_text
            )
        except Exception as tts_err:
            logger.bind(tag=TAG).warning(f"流式融合单结果TTS失败: {tts_err}")
        return kb_text
    if not kb_text and not medical_text:
        return None

    system_prompt = (
        "你是腹透健康助手，融合两条信息源回答。\n"
        "要求：\n"
        "1. 以问题为中心，综合知识库和医疗模型的信息；\n"
        "2. 内容一致则合并，互补则综合，冲突以知识库为准；\n"
        "3. 分点回答（一. 二. 三.），口语表达；\n"
        "4. 使用简体中文输出，控制在700字以内。"
    )
    user_prompt = (
        f"【问题】{question}\n"
        f"【知识库】{kb_text}\n"
        f"【医疗模型】{medical_text}\n"
        f"融合以上信息回答患者问题。"
    )

    # 构造对话格式（与 LLMProviderBase.response_no_stream 一致）
    dialogue = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    full_text = ""
    sentence_buf = ""   # 当前累积的句子

    try:
        logger.bind(tag=TAG).info("===========通用LLM开始流式输出融合结果===========")
        for token in conn.llm.response("", dialogue, temperature=0.3, max_tokens=1024):
            if not token:
                continue
            full_text += token
            sentence_buf += token

            # 检测句子结束
            if _SENTENCE_END.search(token):
                # 累积了足够长的句子才送 TTS（避免极短片段）
                clean = sentence_buf.strip()
                if len(clean) >= 3:
                    logger.bind(tag=TAG).debug(
                        f"===========流式融合推送TTS句子: {clean[:50]}..."
                    )
                    try:
                        conn.tts.tts_one_sentence(
                            conn, ContentType.TEXT, content_detail=clean
                        )
                    except Exception as tts_err:
                        logger.bind(tag=TAG).warning(
                            f"===========流式融合TTS推送失败: {tts_err}"
                        )
                sentence_buf = ""
    except Exception as e:
        logger.bind(tag=TAG).error(f"===========流式融合失败: {e}")
        # 如果有已生成的文本，返回它；否则 None
        if len(full_text.strip()) >= 20:
            pass  # 继续下面的剩余文本处理
        else:
            return None

    # 推送剩余的文本（最后一个句子可能没有结束标点）
    remaining = sentence_buf.strip()
    if len(remaining) >= 3:
        try:
            conn.tts.tts_one_sentence(
                conn, ContentType.TEXT, content_detail=remaining
            )
        except Exception as tts_err:
            logger.bind(tag=TAG).warning(
                f"===========流式融合推送剩余文本失败: {tts_err}"
            )

    full_text = full_text.strip()
    if len(full_text) >= 20:
        logger.bind(tag=TAG).info(
            f"===========流式融合完成，完整结果: {full_text}"
        )
        return full_text

    logger.bind(tag=TAG).warning("流式融合结果空或过短")
    return None

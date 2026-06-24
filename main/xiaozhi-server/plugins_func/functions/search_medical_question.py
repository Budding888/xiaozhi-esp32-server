"""
医疗问答插件

由通用LLM的function_call触发，编排完整医疗问答流程：
RAGFlow知识库检索 → 医疗Qwen推理 → 内容安全校验 → 返回给通用LLM润色

依赖：
- RAGFlow知识库：通过 search_from_ragflow 插件查询（Docker运行）
- 医疗Qwen LLM：外部项目 AutoTokenizer.from_pretrained 部署的 Qwen3.5-4B-Medical
- 通用LLM：通过项目现有的 function_call 意图识别触发本插件
"""

from plugins_func.register import register_function, ToolType, ActionResponse, Action
from plugins_func.functions.search_from_ragflow import search_from_ragflow
from plugins_func.functions.search_from_ragflow import search_from_ragflow_v2
from plugins_func.functions.search_from_ragflow import search_from_ragflow_chat
from config.logger import setup_logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

# ============================================================
# 工具描述 — 通用LLM根据此描述判断何时调用 search_medical_question
# ============================================================
MEDICAL_QA_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "search_medical_question",
        "description": "腹透患者医疗问答：当患者询问任何腹透相关医疗健康问题时必须调用此工具。"
                       "涵盖范围包括但不限于："
                       "①饮食营养（吃什么、忌口、食谱、饮水量、蛋白质、钾磷钠）"
                       "②腹透护理（透析操作、管路护理、出口感染、并发症、腹膜炎）"
                       "③体征异常（血压高/低、血糖高/低、体重变化、尿量少、水肿）"
                       "④用药与禁忌（药物相互作用、腹透相关用药注意事项）"
                       "⑤任何与腹透、肾病、透析相关的症状和问题"
                       "重要：只要患者问到腹透、肾病、透析相关的问题，即使你觉得自己知道答案，也必须调用此工具。"
                       "非医疗问题（天气、新闻、音乐、闲聊等）不需要调用此工具",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "患者提出的医疗相关问题原文，完整保留以便获取准确知识库结果"
                }
            },
            "required": ["question"]
        }
    }
}

# 医疗Qwen的system prompt — 基于知识库，逐条覆盖，段落输出
# 注意：MedicalQwen 擅长内容生成而非格式整理，编号分点由通用LLM在REQLLM阶段处理
medical_system_prompt = """你是腹透健康知识问答助手，基于知识库回答患者问题。

【核心原则】
1. 逐条覆盖知识库中的每一个要点，不得遗漏任何一条；
2. 知识库信息不足时，用你的医学知识补充完善；
3. 如果知识库内容与问题无关，忽略它，用自身知识回答。

【回答要求】
4. 用通俗易懂的口语表达，内容完整覆盖所有要点；
5. 用连贯的段落回答，确保每个要点都被提及；
6. 直接回答用户问题，不要输出思考过程；
7. 控制在600字以内；
8. 用户均为腹膜透析患者；
9. 使用简体中文。

【结束标记】
回答结束后，另起一行输出 ===END==="""



# Query改写prompt — 将口语化问题转为知识库检索友好的关键词形式
# 注意：改写结果将被用于RAGFlow向量检索，目标是提升检索命中率，
# 而不是生成回答。改写结果应为关键词组合，而非完整回答。
query_system_prompt = """你是专业医疗查询改写专家。
任务：把患者口语提问转换成知识库检索关键词，仅输出关键词，禁止完整解答、禁止多余解释。
要求：
1. 提取核心医学名词，补充标准同义术语；
2. 多个关键词使用英文空格隔开，不要使用其他标点符号分隔；
3. 仅输出一行关键词，无换行、无标点说明、无思考过程；
4. 总长度控制在50字符以内。
5. 使用简体中文回答

示例：
患者问题：腹透患者感冒了应该吃什么药？
优化后的查询：腹膜透析 感冒 用药 注意事项 药物相互作用

患者问题：腹膜透析出口感染怎么处理？
优化后的查询：腹膜透析 出口感染 护理 消毒 处理

患者问题：透析患者血压高饮食要注意什么？
优化后的查询：腹膜透析 高血压 饮食 钾 钠 控制 饮水

患者问题：{question}
优化后的查询："""

# 禁忌词替换规则（按类别分组，更具体的短语放前面）
# 当医疗回答包含以下危险表述时，自动替换为安全措辞
medical_replacements = {
    # ===== 饮水控制 =====
    "不用控制饮水": "遵医嘱控制饮水量",
    "不需要限制饮水": "遵医嘱控制饮水量",
    "不必限制饮水": "遵医嘱控制饮水量",
    "不用限水": "遵医嘱控制饮水量",
    "不限水": "遵医嘱控制饮水量",
    "随意饮水": "遵医嘱控制饮水量",
    "随意喝水": "遵医嘱控制饮水量",
    "大量饮水": "遵医嘱控制饮水量",
    "多喝点水": "遵医嘱适量饮水",
    "多喝水": "遵医嘱适量饮水",
    "多饮水": "遵医嘱适量饮水",
    "多喝汤": "遵医嘱控制液体摄入，汤也计入饮水量",
    "多喝粥": "遵医嘱控制液体摄入，粥也计入饮水量",
    "多喝牛奶": "遵医嘱控制液体及磷摄入",
    # ===== 饮食控制 =====
    "不用忌口": "遵医嘱控制饮食",
    "不需要忌口": "遵医嘱控制饮食",
    "不用控制饮食": "遵医嘱控制饮食",
    "随便吃": "遵医嘱控制饮食",
    "随意吃": "遵医嘱控制饮食",
    "不用限盐": "遵医嘱控制盐摄入",
    "不限盐": "遵医嘱控制盐摄入",
    "不用限钾": "遵医嘱控制钾摄入",
    "不限钾": "遵医嘱控制钾摄入",
    "不用限磷": "遵医嘱控制磷摄入",
    "不限磷": "遵医嘱控制磷摄入",
    "多吃香蕉": "香蕉含钾高，建议遵医嘱控制高钾食物摄入",
    "多吃橙子": "橙子含钾高，建议遵医嘱控制高钾食物摄入",
    "多吃橘子": "橘子含钾高，建议遵医嘱控制高钾食物摄入",
    "多吃土豆": "土豆含钾高，建议遵医嘱控制高钾食物摄入",
    "多吃紫菜": "紫菜含钾高，建议遵医嘱控制高钾食物摄入",
    "多吃坚果": "坚果含钾磷高，建议遵医嘱控制摄入",
    "多吃动物内脏": "动物内脏含磷高，建议遵医嘱控制摄入",
    # ===== 药物管理 =====
    "自行停药": "遵医嘱用药，不可自行停药",
    "自己停药": "遵医嘱用药，不可自行停药",
    "随便停药": "遵医嘱用药，不可自行停药",
    "随意停药": "遵医嘱用药，不可自行停药",
    "不用吃药": "遵医嘱按时服药",
    "不用服药": "遵医嘱按时服药",
    "加大药量": "遵医嘱调整剂量",
    "增加药量": "遵医嘱调整剂量",
    "减少药量": "遵医嘱调整剂量",
    "减小药量": "遵医嘱调整剂量",
    "不用吃降压药": "降压药需遵医嘱服用，不可自行停用",
    "不用吃降糖药": "降糖药需遵医嘱服用，不可自行停用",
    "不用吃抗生素": "抗生素需遵医嘱使用，不可自行停用",
    "不用吃消炎药": "消炎药需遵医嘱使用",
    # ===== 透析治疗 =====
    "停止透析": "遵医嘱坚持透析治疗",
    "不用透析": "遵医嘱坚持透析治疗",
    "不做透析": "遵医嘱坚持透析治疗",
    "不做腹透": "遵医嘱坚持腹透治疗",
    "减少透析": "遵医嘱规律透析，不可自行减少",
    "减少透析次数": "遵医嘱规律透析，不可自行减少",
    "减少腹透": "遵医嘱规律腹透，不可自行减少",
    "减少腹透次": "遵医嘱规律腹透，不可自行减少",
    "不用换液": "遵医嘱按时更换腹透液",
    "减少换液": "遵医嘱按时换液，不可自行减少",
    "减少换液次": "遵医嘱按时换液，不可自行减少",
    "腹透液不用换": "遵医嘱按时更换腹透液",
    "不用测超滤": "超滤量是重要监测指标，建议遵医嘱记录",
    "不用记超滤": "超滤量是重要监测指标，建议遵医嘱记录",
    # ===== 监测与复查 =====
    "不用测体重": "体重是干体重评估的重要指标，建议遵医嘱每日测量",
    "体重不用测": "体重是干体重评估的重要指标，建议遵医嘱每日测量",
    "不用测血压": "血压是重要监测指标，建议遵医嘱规律测量",
    "血压不用测": "血压是重要监测指标，建议遵医嘱规律测量",
    "不用测血糖": "血糖是重要监测指标，建议遵医嘱规律测量",
    "不用复查": "建议遵医嘱定期复查",
    "不用检查": "建议遵医嘱定期检查",
    "不用去医院": "建议及时就医",
    "不用就医": "建议及时就医",
    "不用看医生": "建议及时咨询医生",
    # ===== 感染与出口护理 =====
    "不用处理": "建议及时就医处理",
    "自己处理": "建议在医生指导下处理",
    "出口感染没关系": "出口感染需及时就医处理",
    "腹膜炎没关系": "腹膜炎需立即就医处理",
    # ===== 活动与休息 =====
    "剧烈运动": "避免剧烈运动，建议在医生指导下适当活动",
    "不用休息": "注意休息，避免劳累",
    "可以熬夜": "建议规律作息，避免熬夜",
    # ===== 危险症状轻视 =====
    "不用在意": "建议及时咨询医生",
    "不用管它": "建议及时咨询医生",
    "不用太担心": "如有不适建议及时就医",
    "不用担心": "如有不适建议及时就医",
}


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
        return ActionResponse(Action.RESPONSE, None, "请告诉我您的医疗问题")

    logger.bind(tag=TAG).info(f"===========触发腹透患者医疗问答(search_medical_question)===========，问题: {question}")

    # ===== 阶段0：健康检查 =====
    # 快速检测 MedicalQwen 是否存活，决定是否走完整流水线
    medical_config = _get_medical_config()
    logger.bind(tag=TAG).info(f"===========MedicalQwen配置参数medical_config===========: {medical_config}")
    if medical_config:
        from core.providers.llm.medical_qwen.medical_qwen import LLMProvider
        qwen_healthy = LLMProvider.health_check(medical_config)
        logger.bind(tag=TAG).info(f"===========MedicalQwen 健康检查结果: {'正常' if qwen_healthy else '【不可用，进入降级路径】'}")
    else:
        qwen_healthy = False
        logger.bind(tag=TAG).warning("===========MedicalQwen未配置，【进入降级路径】===========")

    if qwen_healthy:
        return _normal_medical_flow(conn, question)
    else:
        return _fallback_medical_flow(conn, question)


def _normal_medical_flow(conn, question):
    """
    正常医疗问答流水线（MedicalQwen 健康时走此路径）

    流程：Query改写 → RAGFlow检索 → 知识压缩 → MedicalQwen推理 → 校验
    """
    import re

    # ===== 阶段1：给用户确认回复 =====
    clean_question = re.sub(r'[^一-鿿A-Za-z0-9]', '', question).strip() or question
    _send_progress_tts(conn, f"好的。")
    _send_progress_tts(conn, f"正在查询关于{clean_question}的问题，请稍候。")

    # ===== 阶段2：查询RAGFlow知识库（含Query改写、RAGFlow检索、知识压缩）=====
    _send_progress_tts(conn, "正在检索知识库。")
    knowledge_context = _query_knowledge_base(conn, question)

    # ===== 阶段3：告知用户准备输出结果 =====
    # 注意：此时才播报"已查询到结果"，确保不误导用户
    _send_progress_tts(conn, "已为您查询到以下医疗信息。")
    # _call_medical_qwen 内部已调用 _medical_verify 追加免责声明，
    # 此处不再重复调用，避免双重免责声明
    medical_answer = _call_medical_qwen(conn, question, knowledge_context)
    logger.bind(tag=TAG).info(f"===========医疗大模型回答结果===========：{medical_answer}")
    if not medical_answer:
        return ActionResponse(
            Action.RESPONSE,
            None,
            "医疗系统繁忙，请稍后再试",
        )

    logger.bind(tag=TAG).info(f"===========医疗问答完成，回答长度: {len(medical_answer)} 字符===========")

    # 返回给通用LLM做最终话术润色
    return ActionResponse(Action.REQLLM, medical_answer, None)


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

    # ===== 阶段1：给用户确认回复 =====
    clean_question = re.sub(r'[^一-鿿A-Za-z0-9]', '', question).strip() or question
    _send_progress_tts(conn, f"好的。")
    _send_progress_tts(conn, f"正在查询关于{clean_question}的问题，请稍候。")
    _send_progress_tts(conn, "正在检索知识库。")

    # ===== 阶段2：直接查RAGFlow（跳过Query改写，因为8106已挂）=====
    try:
        from plugins_func.functions.search_from_ragflow import search_from_ragflow_v2
        rag_result = search_from_ragflow_v2(conn, question=question)

        if rag_result and rag_result.action == Action.REQLLM and rag_result.result:
            # Level 1：有知识库结果 → 通用LLM整理后回答
            knowledge_text = _strip_ragflow_markdown(rag_result.result.strip())
            if knowledge_text:
                logger.bind(tag=TAG).info(f"============【降级路径：RAGFlow】 返回内容，长度: {len(knowledge_text)} 字符============")
                _send_progress_tts(conn, "已查询到相关知识，正在整理回答。")
                fallback_answer = _fallback_answer_with_llm(
                    conn, question, knowledge_text
                )
                if fallback_answer:
                    fallback_answer = _medical_verify(fallback_answer)
                    return ActionResponse(Action.RESPONSE, fallback_answer, None)
    except Exception as e:
        logger.bind(tag=TAG).error(f"============【降级路径：RAGFlow】 查询失败: {e}")

    # Level 2：无RAGFlow结果 → 通用LLM基于自身知识回答
    logger.bind(tag=TAG).info("============【降级路径：RAGFlow】 无结果，使用通用LLM自身知识============")
    _send_progress_tts(conn, "正在为您解答，请稍候。")
    fallback_answer = _fallback_answer_with_llm(conn, question, None)
    if fallback_answer:
        fallback_answer = _medical_verify(fallback_answer)
        return ActionResponse(Action.RESPONSE, fallback_answer, None)

    # Level 3：一切不可用
    logger.bind(tag=TAG).error("============降级路径全部失败============")
    return ActionResponse(Action.RESPONSE, None, "医疗系统繁忙，请稍后再试")


def _fallback_answer_with_llm(conn, question, knowledge_text):
    """
    用通用LLM回答医疗问题（降级路径）

    通过 conn.llm.response_no_stream() 调用通用LLM非流式接口，
    不走 function_call 路径，避免递归调用。

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
            logger.bind(tag=TAG).info(f"============【降级路径：通用LLM】回答成功，长度: {len(cleaned)} 字符============")
            return cleaned
        logger.bind(tag=TAG).warning("============【降级路径：通用LLM】返回空内容============")
    except Exception as e:
        logger.bind(tag=TAG).error(f"============降级路径通用LLM调用失败: {e}")

    return None


def _query_knowledge_base(conn, question):
    """
    查询RAGFlow知识库（含Query改写优化）

    流程：
        1. 将患者口语化问题改写为检索友好形式（方案2：Query改写）
        2. 用改写后的query检索RAGFlow
        3. 清理RAGFlow返回的markdown格式

    如果RAGFlow不可用或未返回结果，返回空字符串（医疗Qwen将基于自身知识回答）。

    Args:
        conn: 连接处理器
        question: 查询问题

    Returns:
        str: 知识库检索结果文本，为空时表示无结果或查询失败
    """
    try:
        # Step 0: Query改写 —— 将口语化问题转为检索友好形式
        optimized_query = _optimize_rag_query(conn, question)
        search_query = optimized_query or question
        if optimized_query:
            logger.bind(tag=TAG).info( f"===========用户Query改写成功: 「原始问题：{question}」 → 「优化后问题：{optimized_query}」")
        else:
            logger.bind(tag=TAG).info(f"===========用户Query改写未生效，使用原始问题检索: 「{question}」" )

        # Step 1: 用改写后的query检索RAGFlow
        # 调用知识库插件进行检索
        rag_result = search_from_ragflow_v2(conn, question=search_query)
        logger.bind(tag=TAG).info( f"===========RAGFlow检索【初步处理之后】的结果===========: 「{rag_result.result}」")

        if rag_result.action == Action.REQLLM and rag_result.result:
            raw_text = rag_result.result.strip()
            # 清理RAGFlow返回的markdown格式，提取纯文本供TTS朗读
            knowledge_text = _strip_ragflow_markdown(raw_text)
            logger.bind(tag=TAG).info(f"============RAGFlow返回内容长度: {len(knowledge_text)} 字符============" )

            # Step 2: 用通用LLM压缩知识库内容（过长时）
            # 通用LLM上下文窗口远大于MedicalQwen(2K)，适合做摘要整理
            compressed_rag_result = _compress_knowledge(conn, question, knowledge_text)
            if compressed_rag_result and compressed_rag_result != knowledge_text:
                ratio = len(compressed_rag_result) / len(knowledge_text) * 100
                logger.bind(tag=TAG).info(f"============知识库压缩完成: 从{len(knowledge_text)} 压缩到--→{len(compressed_rag_result)} 字符 "f"--→压缩率为：{ratio:.0f}%")
                return compressed_rag_result

            # 压缩失败或未执行（内容不长），返回原始知识文本
            return knowledge_text
        logger.bind(tag=TAG).warning("============RAGFlow【未返回有效结果】============")
    except Exception as e:
        logger.bind(tag=TAG).error(f"============RAGFlow【查询失败】: {e}")

    return ""


def _compress_knowledge(conn, question, knowledge_text):
    """
    用通用LLM压缩知识库内容，使其简洁有序，适配MedicalQwen的小上下文窗口

    通用LLM（通常 8K~32K 上下文）将杂乱冗长的知识库结果整理为简洁摘要，
    再送入 MedicalQwen（仅 2K 上下文）做医疗推理，避免 token 超限。

    Args:
        conn: 连接处理器（通过 conn.llm 访问通用LLM）
        question: 患者原始问题
        knowledge_text: RAGFlow返回的原始知识库文本

    Returns:
        str: 压缩后的知识摘要，失败时返回空字符串（调用方用原始内容降级）
    """
    # 知识库内容不长时不需要压缩
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
        # 使用通用LLM的非流式接口直接调用，不走function_call路径
        # 不会触发工具调用，无递归风险
        logger.bind(tag=TAG).info(f"============使用通用LLM整理知识库检索结果============：system_prompt：{system_prompt} → user_prompt：{user_prompt}")
        compressed = conn.llm.response_no_stream(system_prompt, user_prompt)
        logger.bind(tag=TAG).info(f"============使用通用LLM整理知识库检索结果【整理之后的结果】============：{compressed}")
        if compressed:
            # 剔除大模型输出前后多余空行、空格。
            cleaned = compressed.strip()
            # 压缩后有效内容至少 30 字符才认为压缩成功，否则放弃压缩、改用原始知识库文本
            if len(cleaned) >= 30:
                logger.bind(tag=TAG).info(f"============使用通用LLM压缩知识库检索结果【成功】============: {len(knowledge_text)}→{len(cleaned)} 字符")
                return cleaned
            logger.bind(tag=TAG).warning(f"============知识库压缩结果过短({len(cleaned)}字符)，使用原始内容============")
        else:
            logger.bind(tag=TAG).warning("============知识库压缩返回空，使用原始内容============")
    except Exception as e:
        logger.bind(tag=TAG).error(f"============知识库压缩失败: {e}")

    return ""


def _get_medical_config():
    """
    从 config.yaml 读取 MedicalQwen 配置

    独立函数，供 health_check、_optimize_rag_query、_call_medical_qwen 共用。
    直接在本地读取文件，不依赖 conn.config，避免远程配置覆盖。

    Returns:
        dict | None: MedicalQwen 配置字典，未找到时返回 None
    """
    import yaml
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            file_config = yaml.safe_load(f)
        medical_config = file_config.get("LLM", {}).get("MedicalQwen")
        return medical_config
    except Exception as e:
        logger.bind(tag=TAG).error(f"读取 config.yaml 失败: {e}")
        return None


def _optimize_rag_query(conn, question):
    """
    将患者口语化问题改写为知识库检索友好的关键词形式
    利用MedicalQwen将口语问题转为关键词组合，提升RAGFlow向量检索命中率。
    清洗流水线：去引号 → 合并换行 → 中文分隔符→空格 → 长度校验 → 句子标记检测
    Args:
        conn: 连接处理器
        question: 患者提出的原始问题

    Returns:
        str: 改写后的检索query（空格分隔），失败返回空字符串（降级原始问题）

    1. temperature=0.2
        temperature 控制大模型生成随机性、创造性，取值范围 0 ~ 1：
        -越接近 0：模型输出越稳定、保守、固定，优先选择概率最高的文字，几乎不会发挥、不会乱发挥；
        -越接近 1：模型随机性越强，会选低概率词汇，回答更多变、有创意，适合聊天、文案创作。

        你当前场景为什么设 0.2（极低温度）
        你的需求是标准化关键词提取，不允许模型自由发挥：
        不能随意增减术语、不能变换句式、不能即兴写多余文字；
        同一个患者问题，每次改写输出要高度统一，保证检索向量稳定；
        如果调高到 0.7/0.8，模型容易时不时输出完整句子、新增无关词汇，触发后面的标点校验拦截，改写失效。

        参考取值对照
        ---------------------------------------------------------------
        0 ~ 0.3：摘要、关键词提取、查询改写、工具调用、结构化输出（你现在的场景）
        0.4 ~ 0.7：通用问答、医疗科普回复
        0.8 ~ 1.0：创意写作、闲聊、故事生成
        ---------------------------------------------------------------

        2. max_tokens=128 【1 token ≈ 0.5 个汉字】
        限制模型单次最多能生成多少个 token（文字片段），防止无限输出超长内容。
        中文粗略换算：1 token ≈ 0.5 个汉字，128 tokens 大约支持 60 个汉字左右。
        适配你的业务规则
        你的 Prompt 明确约束改写关键词控制在 50 字符以内：
        设置 max_tokens=128 留出少量冗余，避免刚好卡 50 字时报截断；
        硬性兜底：哪怕模型不受约束想写长篇大段回答，到 128token 会强制停止；
        配合后面代码 if len(optimized) > 50 二次校验，双重拦截超长文本；
        限制 token 同时减少推理耗时，提升接口响应速度。
    """
    from core.utils import llm as llm_utils

    medical_config = _get_medical_config()
    if not medical_config:
        logger.bind(tag=TAG).warning("MedicalQwen未配置，跳过Query改写")
        return ""

    try:
        medical_llm = llm_utils.create_instance("medical_qwen", medical_config)
    except Exception as e:
        logger.bind(tag=TAG).error(f"创建MedicalQwen实例失败，跳过Query改写: {e}")
        return ""

    query_user_input = f"患者问题：{question}\n优化后的查询："
    try:
        optimized = medical_llm.response_no_stream(
            system_prompt=query_system_prompt,
            user_prompt=query_user_input,
            # 控制大模型生成随机性、创造性
            temperature=0.2,
            # 限制模型单次最多能生成多少个 token（文字片段），防止无限输出超长内容
            max_tokens=128
        )
        logger.bind(tag=TAG).info(f"===========用户Query改写 | 原始问句:「{question}」→ 模型原始输出:「{optimized}」")

        if not optimized:
            logger.bind(tag=TAG).warning("===========用户Query改写 | 模型返回为空，降级原始问题")
            return ""

        # ===== 清洗流水线 =====
        # Step 1: 去引号、首尾空白
        optimized = optimized.strip().strip('"').strip("'")
        # Step 2: 换行合并为空格
        optimized = " ".join(optimized.splitlines())
        # Step 3: 中文分隔符统一替换为空格（模型习惯输出逗号而非空格）
        for sep in ["，", "、", ";", "；"]:
            optimized = optimized.replace(sep, " ")
        # Step 4: 去处尾部的标点符号
        optimized = strip_end_punctuation(optimized)
        # Step 5: 合并连续空格
        optimized = " ".join(optimized.split())
        logger.bind(tag=TAG).info(f"===========用户Query改写 | 清洗后:「{optimized}」(len={len(optimized)})")

        # ===== 校验流水线 =====
        # 1) 最短长度 4 字符（至少2个双字关键词）
        if len(optimized) < 4:
            logger.bind(tag=TAG).warning(f"===========用户Query改写 | 结果过短({len(optimized)}): '{optimized}'，降级原始问题")
            return ""
        # 2) 最长 50 字符（超出说明输出了完整句子/段落）
        if len(optimized) > 50:
            logger.bind(tag=TAG).warning(f"===========用户Query改写 | 结果过长({len(optimized)}字符)，疑似完整回答，降级原始问题")
            return ""
        # 3) 句子标记检测：句号/问号/感叹号/冒号 → 表明模型输出了完整句子而非关键词
        #    （逗号、顿号、分号已在清洗阶段替换，无需在此拦截）
        sentence_markers = ["。", "？", "！", "："]
        if any(marker in optimized for marker in sentence_markers):
            logger.bind(tag=TAG).warning(
                f"===========用户Query改写 | 含完整句子标点，判定为回答文本，降级原始问题。片段: {optimized[:120]}"
            )
            return ""
        return optimized
    except Exception as e:
        logger.bind(tag=TAG).error(f"===========用户Query改写 | 调用失败: {e}")
        return ""

# 去除末尾标点
def strip_end_punctuation(text: str) -> str:
    import re
    # 匹配末尾任意中英文标点，循环删除直到末尾无标点
    # [\u3000-\u303F\uFF00-\uFF60\.,;:!?。，；：？！、] 覆盖绝大多数标点
    pattern = r'[^\w\s]$'
    while re.search(r'[\u3000-\u303F\uFF00-\uFF60\.,;:!?。，；：？！、]$', text):
        text = text[:-1].strip()
    return text

def _strip_ragflow_markdown(text: str) -> str:
    """
    清理RAGFlow返回结果中的markdown格式符号

    RAGFlow返回的格式示例：
        # 关于问题【xxx】查到知识库如下
        ```内容块...```

    清理后只保留纯文本内容，去掉 #、【】、```、\n 等格式符号。

    Args:
        text: RAGFlow返回的原始文本

    Returns:
        str: 清理后的纯文本
    """
    import re

    # 去掉开头的 "# 关于问题..." 标题行
    text = re.sub(r"^#\s*关于问题.*?如下\s*\n?", "", text)

    # 去掉 ``` 代码块标记
    text = text.replace("```", "")

    # 去掉【】以及其中的内容（如【腹膜炎的并发症有哪些？】）
    text = re.sub(r"【[^】]*】", "", text)

    # 将多个连续换行压缩为单个
    text = re.sub(r"\n{2,}", "\n", text)

    # 去掉开头结尾的空白
    text = text.strip()

    return text


def _call_medical_qwen(conn, question, knowledge_context):
    """
    调用医疗Qwen LLM进行推理

    通过项目工厂模式创建MedicalQwen Provider实例，
    将知识库上下文和患者问题构造为Prompt后请求医疗Qwen生成回答。

    Args:
        conn: 连接处理器
        question: 患者问题
        knowledge_context: RAGFlow检索的知识库内容（可能为空）

    Returns:
        str: 医疗Qwen生成的回答文本，失败时返回None
    """
    from core.utils import llm as llm_utils
    from core.providers.tts.dto.dto import ContentType, TTSMessageDTO, SentenceType

    # 使用共享函数读取MedicalQwen配置，避免重复读取逻辑
    medical_config = _get_medical_config()
    if not medical_config:
        logger.bind(tag=TAG).error("============config.yaml 中未找到 MedicalQwen 配置============")
        return None
    logger.bind(tag=TAG).info(f"从 config.yaml 读取 MedicalQwen 配置: {medical_config.get('base_url')}")
    logger.bind(tag=TAG).info(f"============【调用医疗LLM进行推理】medical_config============: {medical_config}")

    try:
        medical_llm = llm_utils.create_instance("medical_qwen", medical_config)
    except Exception as e:
        logger.bind(tag=TAG).error(f"创建 MedicalQwen 实例失败: {e}")
        return None

    # 构建用户prompt：要求逐条覆盖知识库全部要点，段落输出，加结束标记
    if knowledge_context:
        user_prompt = f"""【知识库参考内容】
        {knowledge_context}

        【患者问题】
        {question}

        回答要求：
        1. 逐条覆盖以上参考内容中的每一个要点，全部保留、不得遗漏；
        2. 用连贯的段落回答，确保每个要点都被自然提及；
        3. 全部要点覆盖完后，如果知识库不足以完全回答问题，补充你的医学知识；
        4. 如果知识库已完整覆盖，则无需补充。
        5. 回答结束后，另起一行输出 ===END==="""
    else:
        user_prompt = f"""【患者问题】 {question} 回答结束后，另起一行输出 ===END==="""

    try:
        # 构建对话消息列表，使用流式 response() 替代非流式 response_no_stream()
        dialogue = [
            {"role": "system", "content": medical_system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        full_answer = ""
        for chunk in medical_llm.response("", dialogue):
            if not chunk:
                continue
            full_answer += chunk
            # 流式输出：每个 token 块实时送入 TTS 队列
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
            # 只做禁忌词替换，不追加免责声明（免责声明由调用方以独立 TTS 消息发送，带停顿）
            verified = _medical_verify(full_answer.strip())
            return verified
        logger.bind(tag=TAG).warning("===========MedicalQwen=========== 返回空内容")
        return None

    except Exception as e:
        logger.bind(tag=TAG).error(f"===========MedicalQwen=========== 调用失败: {e}")
        return None


def _send_disclaimer_tts(conn):
    """
    以独立 TTS 消息发送免责声明（带停顿，避免与主回答紧贴）

    在 answer 的 TTS 已入队后、LAST 标记发送前调用。
    内部 sleep 1 秒形成播报间隙，消费者线程在队列空时自然停顿。
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


def _get_disclaimer_text() -> str:
    """
    从 config.yaml 读取免责声明文本

    从 MedicalQwen.disclaimer 配置项读取，如果未配置则返回默认值。

    Returns:
        str: 免责声明文本（不含 \n\n⚠️ 前缀，调用方自行添加）
    """
    medical_config = _get_medical_config()
    if medical_config:
        disclaimer = medical_config.get("disclaimer", "")
        if disclaimer:
            return disclaimer.strip()
    # 默认值
    return "温馨提示：以上内容仅供参考，不构成医疗诊断及治疗建议，不能替代专业诊疗，如有不适请及时就医并遵从专业医生指导。"


def _medical_verify(text):
    """
    医疗内容安全校验

    对医疗Qwen或通用LLM的输出进行安全校验：
    1. 禁忌词过滤/替换（如"不限水"等危险表述）
    2. 注意：免责声明不在此追加，由调用方以独立 TTS 消息发送

    Args:
        text: 医疗回答文本

    Returns:
        str: 校验处理后的安全文本
    """
    if not text:
        return text

    # 禁忌词替换
    for old, new in medical_replacements.items():
        if old in text:
            logger.bind(tag=TAG).warning(f"医疗回答含禁忌词「{old}」，已替换")
            text = text.replace(old, new)

    # 从配置文件读取免责声明并追加
    disclaimer = _get_disclaimer_text()
    text += f"\n\n⚠️ {disclaimer}"

    return text

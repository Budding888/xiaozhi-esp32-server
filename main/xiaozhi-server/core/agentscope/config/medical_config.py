"""
医疗问答配置常量

包含禁忌词替换规则、System Prompt、Query改写Prompt等医疗问答相关配置，
从 search_medical_question.py 抽取的独立模块。
"""

from typing import Optional, TYPE_CHECKING

from config.logger import setup_logging

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
9. 回答完整通顺，无残缺短句；
10. 使用简体中文。
"""

medical_system_prompt_v2 = (
    "你是一名专业的医疗健康助手。\n"
    "约束条件：\n"
    "1. 直接回答用户问题，不要输出任何分析步骤或内部思考过程\n"
    "2. 同一个问题中可能存在多个小问题，拆分后逐个回答\n"
    "3. 用户均为腹膜透析患者\n"
    "4. 回答要简洁、准确、直接、控制在600字以内\n"
    "5. 不要给出重复的回答\n"
    "6. 回答完整通顺，无残缺短句\n"
    "7. 使用简体中文"
)

# Query改写prompt — 将口语化问题转为知识库检索友好的关键词形式
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

# ============================================================
# 禁忌词替换规则（按类别分组，更具体的短语放前面）
# ============================================================
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
    "不要遵医嘱": "建议及时咨询医生",
    "不要遵循医嘱": "建议及时咨询医生",
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


def _get_medical_config(conn: Optional["ConnectionHandler"] = None) -> Optional[dict]:
    """
    从 conn.config 或 config.yaml 读取 MedicalQwen 配置

    优先从 conn.config 读取（内存中已合并的配置），
    兜底直接读取 config.yaml 文件（兼容旧代码）。

    Args:
        conn: ConnectionHandler 实例（可选），提供时优先使用其 config 属性

    Returns:
        dict | None: MedicalQwen 配置字典，未找到时返回 None
    """
    import yaml

    # 优先从 conn.config 读取（内存中已合并的配置）
    if conn is not None:
        try:
            conn_config = getattr(conn, "config", None)
            if conn_config is not None:
                medical_config = conn_config.get("LLM", {}).get("MedicalQwen")
                if medical_config:
                    return medical_config
        except Exception as e:
            logger.bind(tag=TAG).debug(f"从 conn.config 读取 MedicalQwen 配置失败: {e}")

    # 兜底：直接读取 config.yaml 文件
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            file_config = yaml.safe_load(f)
        medical_config = file_config.get("LLM", {}).get("MedicalQwen")
        return medical_config
    except Exception as e:
        logger.bind(tag=TAG).error(f"读取 config.yaml 失败: {e}")
        return None


def _get_disclaimer_text(conn: Optional["ConnectionHandler"] = None) -> str:
    """
    从配置读取免责声明文本

    Args:
        conn: ConnectionHandler 实例（可选），提供时通过 _get_medical_config(conn) 读取

    Returns:
        str: 免责声明文本
    """
    medical_config = _get_medical_config(conn)
    if medical_config:
        disclaimer = medical_config.get("disclaimer", "")
        if disclaimer:
            return disclaimer.strip()
    return "郑重申明：以上内容仅作为知识问答，不构成医疗诊断及治疗建议与参考，不能替代专业诊疗，如有不适请及时就医并遵从专业医生指导。"


def _medical_verify(text: str, conn: Optional["ConnectionHandler"] = None) -> str:
    """
    医疗内容安全校验

    对医疗Qwen或通用LLM的输出进行安全校验：
    1. 禁忌词过滤/替换（如"不限水"等危险表述）

    注意：免责声明由 receiveAudioHandle.py 通过 _send_disclaimer_tts()
    以独立 TTS 消息发送（带停顿，播报节奏更好），不在本函数追加到文本中，
    避免与 _send_disclaimer_tts 重复。

    Args:
        text: 医疗回答文本
        conn: ConnectionHandler 实例（可选）

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

    return text


def _strip_ragflow_markdown(text: str) -> str:
    """
    清理RAGFlow返回结果中的markdown格式符号

    Args:
        text: RAGFlow返回的原始文本（None 安全）

    Returns:
        str: 清理后的纯文本，None 输入返回空字符串
    """
    import re

    if not text:
        return ""

    # 去掉 ``` 代码块标记
    text = text.replace("```", "")

    # 去掉【】符号本身，保留其中的内容（【】是 RAGFlow chunk 包装标记，不是内容）
    text = re.sub(r"【([^】]*)】", r"\1", text)

    # 将多个连续换行压缩为单个
    text = re.sub(r"\n{2,}", "\n", text)

    # 去掉开头结尾的空白
    text = text.strip()

    return text


def strip_end_punctuation(text: str) -> str:
    """
    去除字符串末尾的中英文标点符号

    Args:
        text: 输入字符串

    Returns:
        str: 去除末尾标点后的字符串
    """
    import re
    while re.search(r'[　-〿＀-｠\.,;:!?。，；：？！、]$', text):
        text = text[:-1].strip()
    return text

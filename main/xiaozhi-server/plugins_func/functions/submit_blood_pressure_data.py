"""
血压数据上报插件
用户通过语音上报血压数据，调用外部系统的血压更新API接口完成数据记录
"""
from datetime import datetime
import os

import requests
import yaml

from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

PLUGIN_NAME = "submit_blood_pressure_data"

# 命中这些关键字的 api_url 视为未正确配置的占位地址（智控台常下放此类默认值）
_PLACEHOLDER_MARKERS = (
    "rpm.com",
    "weight.submit",
    "submitBloodGlucose",
    "submitWeight",
    "submitHeartRate",
    "submitUrine",
    "submitblood_glucose",
    "submitheart_rate",
    "submiturine_volume",
    "你的",
    "xxx",
)


def _is_placeholder_url(url) -> bool:
    """判断 api_url 是否为占位/未正确配置地址"""
    if not url or not isinstance(url, str):
        return True
    low = url.lower()
    return any(m in low for m in _PLACEHOLDER_MARKERS)


def _get_effective_plugin_config(conn: "ConnectionHandler") -> dict:
    """获取插件配置。

    运行时配置（智控台下放）优先；但当智控台只下放了占位地址/缺少 api_key 时，
    回退到本地 config.yaml 中的插件配置，避免命中默认占位地址导致上报失败。
    """
    effective = conn.config.get("plugins", {}).get(PLUGIN_NAME, {})
    if not isinstance(effective, dict):
        effective = {}

    local = {}
    try:
        project_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        with open(
            os.path.join(project_dir, "config.yaml"), "r", encoding="utf-8"
        ) as f:
            local = yaml.safe_load(f).get("plugins", {}).get(PLUGIN_NAME, {}) or {}
    except Exception as e:
        logger.bind(tag=TAG).warning(f"读取本地 config.yaml 插件配置失败: {e}")

    merged = dict(local)
    # 运行时（智控台）配置覆盖本地配置；但占位/无效的 url 与缺失的 api_key 不覆盖
    for key in ("api_url", "url"):
        if key in effective and not _is_placeholder_url(effective.get(key)):
            merged[key] = effective[key]
    if effective.get("api_key"):
        merged["api_key"] = effective["api_key"]
    for key, value in effective.items():
        if key not in ("api_url", "url", "api_key"):
            merged[key] = value
    return merged

submit_blood_pressure_data_function_desc = {
    "type": "function",
    "function": {
        "name": "submit_blood_pressure_data",
        "description": (
            "用于用户上报血压数据"
            "用户者说'我要上报血压数据，今天的高压是150、低压是120'、'下机后高压是150、低压是120，请上报血压数据'、'上机前收缩压是150、舒张压是120，请上报'、'我要上报血压，下午血压是150、120'、'我要上报血压，血压是150/120'、'我要上报血压，血压是150和120'、'高压150，低压120，请上报'、'收缩压150，舒张压120，请上报'等与血压记录与上报相关的指令时调用此功能。"
            "注意：1.如果用户说的血压没有明确高压与低压时，将数值大的识别为高压/收缩压/上压，数值小识别为低压/舒张压/下压。2.上报、提交、登记、上传、报上去、提交一下、上报一下、帮我提交、帮我上报、反馈一下、记录、录入、保存、记下来、存一下、帮我记下、录入进去、保存一下等均是同义词。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "systolic": {
                    "type": "number",
                    "description": "高压/收缩压/上压数值，单位为毫米汞柱(mmHg)，如果用户说的血压没有明确高压与低压时，将数值大的识别为高压/收缩压/上压。例如：我的上机前的高压是150，表示高压150毫米汞柱。如果用户说'我的血压是125和155时，高压就是数值大的这一项165，而不是125'",
                },
                "diastolic": {
                    "type": "number",
                    "description":  "低压/舒张压/下压数值，单位为毫米汞柱(mmHg)，如果用户说的血压没有明确高压与低压时，将数值小识别为低压/舒张压/下压。例如：我的上机后的低压是150，表示低压150毫米汞柱。如果用户说'我的血压是135和160时，低压就是数值小的这一项135，而不是160'",
                },
                "remarks": {
                    "type": "string",
                    "description": "备注信息，例如'上机前'、'下机后'、'早上'、'中午'、'下午'、'晚上'等",
                },
            },
            "required": ["systolic", "diastolic"],
        },
    },
}


@register_function("submit_blood_pressure_data", submit_blood_pressure_data_function_desc, ToolType.SYSTEM_CTL)
def submit_blood_pressure_data( conn: "ConnectionHandler", systolic: float, diastolic: float, remarks: str = None):
    """
    上报用户血压数据到外部健康管理系统

    Args:
        conn: 连接处理器，用于获取配置和设备信息
        systolic: 高压/收缩压/上压数值，必填
        diastolic: 低压/舒张压/下压数值，必填
        remarks: 备注信息，可选
    """
    logger.bind(tag=TAG).info(
        f"收到血压上报请求: systolic={systolic}, diastolic={diastolic},  remarks={remarks}"
    )

    # 参数校验
    if not systolic or not diastolic:
        logger.bind(tag=TAG).info("高压数据或低压数据未上报，请检查后重新上报")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="您上报的血压数据上报不完整，高压数据或低压数据未上报，请检查后重新上报"
        )

    if systolic and diastolic and systolic <= diastolic:
        logger.bind(tag=TAG).info(f"低压数据不能大于高压数值异常")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response=f"您上报的血压数值看起来不太合理，请先明确指出哪个是高压、哪个是低压，再重新上报",
        )

    # 读取插件配置：运行时(智控台)配置优先，占位/缺失字段回退到本地 config.yaml
    plugin_config = _get_effective_plugin_config(conn)
    if not plugin_config:
        logger.bind(tag=TAG).info("插件配置参数未配置，请检查")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="插件配置参数未配置，请联系管理员完善设置"
        )

    api_url = plugin_config.get("api_url") or plugin_config.get("url")
    api_key = plugin_config.get("api_key")
    timeout = plugin_config.get("timeout", 20)

    if not api_url or _is_placeholder_url(api_url):
        logger.bind(tag=TAG).info("血压上报API地址未正确配置，请检查")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="血压数据上报API地址暂未配置，请联系管理员完善设置"
        )

    # 构建请求数据
    now = datetime.now()
    date_time_str=now.strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "deviceId": conn.device_id,
        "clientId": conn.client_id,
        "sbpValue": systolic,
        "dbpValue": diastolic,
        "remarks": remarks or "",
        "type": "submit_blood_pressure_data",
        "source": "xiaozhi_voice_assistant",
        "timestamp": date_time_str,
    }

    headers = {
        "Content-Type": "application/json",
        "version": "v1",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    logger.bind(tag=TAG).info(
        f"正在上报血压数据到外部API: {api_url}, payload: {payload}"
    )

    try:
        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=timeout,
        )

        # 校验响应的状态，存在错误码，则返回错误信息
        response.raise_for_status()

        # 处理响应成功时返回信息
        result = response.json()
        logger.bind(tag=TAG).info(f"血压数据上报成功, API响应: {result}")
        return build_success_response(systolic, diastolic, date_time_str, remarks, result)

    except requests.exceptions.ConnectionError as e:
        logger.bind(tag=TAG).error(f"连接血压上报API失败: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="网络连接失败，暂时无法上报血压数据，请稍后再试",
        )

    except requests.exceptions.Timeout as e:
        logger.bind(tag=TAG).error(f"血压上报API请求超时: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="血压数据上报超时，请稍后再试",
        )

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if hasattr(e, "response") else "未知"
        error_detail = ""
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = e.response.text if hasattr(e, "response") else ""
        logger.bind(tag=TAG).error(
            f"血压上报API返回错误, 状态码: {status_code}, 详情: {error_detail}"
        )
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="血压数据上报服务异常，请稍后再试或联系管理员",
        )

    except Exception as e:
        logger.bind(tag=TAG).error(f"血压数据上报发生未知异常: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="血压数据上报失败，请稍后再试",
        )


def build_success_response(systolic, diastolic, date_time_str, remarks, api_result):
    """构建上报成功后的LLM结果文本"""
    result_text = (
        f"用户血压数据已成功上报。\n"
        f"高压值: {systolic}mmHg\n"
        f"低压值: {diastolic}mmHg\n"
        f"上报时间: {date_time_str}\n"
    )
    if remarks:
        result_text += f"备注: {remarks}\n"

    if isinstance(api_result, dict):
        record_id = api_result.get("id") or api_result.get("record_id")
        if record_id:
            result_text += f"记录ID: {record_id}\n"

    result_text += "\n请告知用户血压数据已记录成功，并给予鼓励。"

    logger.bind(tag=TAG).info(
        f"血压数据上报成功, result_text响应: {result_text}"
    )
    return ActionResponse(
        action=Action.REQLLM,
        result=result_text,
        response=None,
    )

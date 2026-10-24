"""
血糖数据上报插件
用户通过语音上报血糖数据，调用外部系统的血糖更新API接口完成数据记录
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

PLUGIN_NAME = "submit_blood_glucose_data"

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

submit_blood_glucose_data_function_desc = {
    "type": "function",
    "function": {
        "name": "submit_blood_glucose_data",
        "description": (
            "用于用户上报血糖数据。"
            "当用户说'我要上报血糖数据，今天的血糖是xxxx mmol/L'、'今天的血糖是xxxx mmol/L，请上报血糖数据'、'今天的血糖是xxxx毫摩尔/升，请上报'、'我要上报血糖，血糖是xxxx毫摩尔/升'等与血糖记录与上报相关的指令时调用此功能。"
            "注意：上报、提交、登记、上传、报上去、提交一下、上报一下、帮我提交、帮我上报、反馈一下、记录、录入、保存、记下来、存一下、帮我记下、录入进去、保存一下等均是同义词。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "blood_glucose": {
                    "type": "number",
                    "description": "血糖数值，单位为毫摩尔/升(mmol/L)。例如：3.9表示3.9mmol/L, 7.8毫摩尔/升表示7.8mmol/L。",
                },
                "remarks": {
                    "type": "string",
                    "description": "备注信息，例如'空腹'、'午饭前'、'午餐前'、'午饭后2小时'、'晚餐前'、'晚餐后2小时'、'睡觉前'等",
                },
            },
            "required": ["blood_glucose"],
        },
    },
}


@register_function("submit_blood_glucose_data", submit_blood_glucose_data_function_desc, ToolType.SYSTEM_CTL)
def submit_blood_glucose_data( conn: "ConnectionHandler", blood_glucose: float, remarks: str = None):
    """
    上报用户血糖数据到外部健康管理系统

    Args:
        conn: 连接处理器，用于获取配置和设备信息
        blood_glucose: 血糖值毫摩尔/升(mmol/L)，必填
        remarks: 备注信息，可选
    """
    logger.bind(tag=TAG).info(
        f"收到血糖上报请求: blood_glucose={blood_glucose},  remarks={remarks}"
    )

    # 参数校验
    if not blood_glucose:
        logger.bind(tag=TAG).info("血糖未上报，请检查后重新上报")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="您上报的血糖数据上报不完整，血糖数值未上报，请检查后重新上报"
        )

    # 参数校验, 有待进一步优化: https://ai.dangbei.com/share/sPqHXtfMWF
    # 危急值警示文案（存在时，上报后语音一并提示用户）
    critical_warning = None

    # 无效数据（物理上不可能，录入错误）
    if blood_glucose <= 0:
        logger.bind(tag=TAG).info(f"血糖数值异常(非法值): {blood_glucose}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response=f"您上报的血糖数值{blood_glucose}看起来不太合理，请确认后重新上报",
        )
    # 危急值（数值存在，但需要警示，不拒绝上报）
    elif blood_glucose > 20:
        logger.bind(tag=TAG).warning(f"血糖为危急高值: {blood_glucose}")
        critical_warning = (
            f"本次录入血糖{blood_glucose}mmol/L，数值明显偏高。"
            f"记录已保存，建议复测血糖，并尽快咨询主管医生。"
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
    use_mock = plugin_config.get("use_mock", False)

    if not api_url or _is_placeholder_url(api_url):
        logger.bind(tag=TAG).info("血糖上报API地址未正确配置，请检查")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="血糖数据上报API地址暂未配置，请联系管理员完善设置"
        )

    # 构建请求数据
    now = datetime.now()
    date_time_str=now.strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "deviceId": conn.device_id,
        "clientId": conn.client_id,
        "value": blood_glucose,
        "remarks": remarks or "",
        "type": "submit_blood_glucose_data",
        "source": "xiaozhi_voice_assistant",
        "timestamp": date_time_str,
    }

    headers = {
        "Content-Type": "application/json",
        "version": "v1",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # 是否使用mock数据（开发/测试阶段使用，避免依赖真实外部API）
    if use_mock:
        return _handle_mock_response(
            conn, blood_glucose, date_time_str, remarks, critical_warning
        )

    logger.bind(tag=TAG).info(
        f"正在上报血糖数据到外部API: {api_url}, payload: {payload}"
    )

    try:
        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()

        result = response.json()
        logger.bind(tag=TAG).info(f"血糖数据上报成功, API响应: {result}")

        return _build_success_response(
            blood_glucose, date_time_str, remarks, result, critical_warning
        )

    except requests.exceptions.ConnectionError as e:
        logger.bind(tag=TAG).error(f"连接血糖上报API失败: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="网络连接失败，暂时无法上报血糖数据，请稍后再试",
        )

    except requests.exceptions.Timeout as e:
        logger.bind(tag=TAG).error(f"血糖上报API请求超时: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="血糖数据上报超时，请稍后再试",
        )

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if hasattr(e, "response") else "未知"
        error_detail = ""
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = e.response.text if hasattr(e, "response") else ""
        logger.bind(tag=TAG).error(
            f"血糖上报API返回错误, 状态码: {status_code}, 详情: {error_detail}"
        )
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="血糖数据上报服务异常，请稍后再试或联系管理员",
        )

    except Exception as e:
        logger.bind(tag=TAG).error(f"血糖数据上报发生未知异常: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="血糖数据上报失败，请稍后再试",
        )


def _handle_mock_response(conn, blood_glucose, date_time_str, remarks, critical_warning=None):
    """处理mock响应，模拟外部API返回"""
    import uuid
    from datetime import timedelta

    mock_record_id = f"blood_glucose-{uuid.uuid4().hex[:12].upper()}"
    mock_patient_name = f"用户{conn.device_id[-4:]}" if conn.device_id else "未知用户"

    mock_result = {
        "code": 0,
        "message": "success",
        "id": mock_record_id,
        "record_id": mock_record_id,
        "patient_id": conn.device_id,
        "patient_name": mock_patient_name,
        "value": blood_glucose,
        "remarks": remarks or "",
        "unit": "kg",
        "status": "confirmed",
        "created_at": date_time_str,
        "next_measure_reminder": (
            datetime.now() + timedelta(days=1)
        ).strftime("%Y-%m-%d %H:%M:%S"),
    }

    logger.bind(tag=TAG).info(
        f"【Mock】血糖数据上报模拟成功, mock响应: {mock_result}"
    )

    return _build_success_response(
        blood_glucose, date_time_str, remarks, mock_result, critical_warning
    )


def _build_success_response(blood_glucose, date_time_str, remarks, api_result, critical_warning=None):
    """构建上报成功后的LLM结果文本"""
    result_text = (
        f"用户血糖数据已成功上报。\n"
        f"血糖: {blood_glucose}mmol/L\n"
        f"上报时间: {date_time_str}\n"
    )
    if remarks:
        result_text += f"备注: {remarks}\n"

    if isinstance(api_result, dict):
        record_id = api_result.get("id") or api_result.get("record_id")
        if record_id:
            result_text += f"记录ID: {record_id}\n"

    if critical_warning:
        result_text += f"\n重要提示：{critical_warning}"

    result_text += "\n请告知用户血糖数据已记录成功，并给予鼓励。"

    return ActionResponse(
        action=Action.REQLLM,
        result=result_text,
        response=None,
    )

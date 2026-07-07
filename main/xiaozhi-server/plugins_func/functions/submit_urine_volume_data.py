"""
尿量数据上报插件
用户通过语音上报尿量数据，调用外部系统的尿量更新API接口完成数据记录
"""
from datetime import datetime
import requests
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

submit_urine_volume_data_function_desc = {
    "type": "function",
    "function": {
        "name": "submit_urine_volume_data",
        "description": (
            "用于用户上报尿量数据。"
            "用户者说'我要上报尿量数据，今天的尿量是xxxx毫升(ml)'、'我的尿量是xxxx毫升，请上报尿量'、'尿量xxxx毫升(ml)，请上报'、'我要上报尿量，尿量是xxxx毫升(ml)'等与尿量记录与上报相关的指令时调用此功能。"
            "注意：上报、提交、登记、报上去、提交一下、上报一下、帮我提交、帮我上报、反馈一下、记录、录入、保存、记下来、存一下、帮我记下、录入进去、保存一下等均是同义词。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "urine_volume": {
                    "type": "number",
                    "description": "尿量数值，单位为毫升(ml)。例如：39表示39毫升(ml)。",
                },
                "remarks": {
                    "type": "string",
                    "description": "备注信息，例如'上机前'、'下机后'、'早上'、'中午'、'下午'、'晚上'等",
                },
            },
            "required": ["urine_volume"],
        },
    },
}


@register_function("submit_urine_volume_data", submit_urine_volume_data_function_desc, ToolType.SYSTEM_CTL)
def submit_urine_volume_data( conn: "ConnectionHandler", urine_volume: float, remarks: str = None):
    """
    上报用户尿量数据到外部健康管理系统

    Args:
        conn: 连接处理器，用于获取配置和设备信息
        urine_volume: 尿量值毫升(ml)，必填
        remarks: 备注信息，可选
    """
    logger.bind(tag=TAG).info(
        f"收到尿量上报请求: urine_volume={urine_volume},  remarks={remarks}"
    )

    # 参数校验
    if not urine_volume:
        logger.bind(tag=TAG).info("尿量未上报，请检查后重新上报")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="您上报的尿量数据上报不完整，尿量数值未上报，请检查后重新上报"
        )

    # 参数校验, 有待进一步优化: https://ai.dangbei.com/share/sPqHXtfMWF
    # 根据尿量值是否给出建议,有待确认与优化
    if urine_volume <= 0:
        logger.bind(tag=TAG).info(f"尿量数值异常: {urine_volume}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response=f"您上报的尿量数值{urine_volume}看起来不太合理，请确认后重新上报",
        )

    # 从config.yaml文件的插件配置中读取外部API信息
    plugin_config = conn.config.get("plugins", {}).get("submit_urine_volume_data", {})
    api_url = plugin_config.get("api_url", "https://rpm.com/api/submiturine_volume")
    api_key = plugin_config.get("api_key", "XXX")
    timeout = plugin_config.get("timeout", 20)
    use_mock = plugin_config.get("use_mock", True)

    if not plugin_config:
        logger.bind(tag=TAG).info("插件配置参数未配置，请检查")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="插件配置参数未配置，请联系管理员完善设置"
        )
    if not api_url:
        logger.bind(tag=TAG).info("尿量上报API地址未正确配置，请检查")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="尿量数据上报API地址暂未配置，请联系管理员完善设置"
        )
    if not api_key:
        logger.bind(tag=TAG).info("尿量上报API key未正确配置，请检查")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="尿量数据上报API key暂未配置，请联系管理员完善设置"
        )

    # 构建请求数据
    now = datetime.now()
    date_time_str=now.strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "device_id": conn.device_id,
        "patient_id": conn.device_id,
        "value": urine_volume,
        "remarks": remarks or "",
        "type": "submit_urine_volume_data",
        "source": "xiaozhi_voice_assistant",
        "timestamp": date_time_str,
    }

    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # 是否使用mock数据（开发/测试阶段使用，避免依赖真实外部API）
    if use_mock:
        return _handle_mock_response(conn, urine_volume, date_time_str, remarks)

    logger.bind(tag=TAG).info(
        f"正在上报尿量数据到外部API: {api_url}, payload: {payload}"
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
        logger.bind(tag=TAG).info(f"尿量数据上报成功, API响应: {result}")

        return _build_success_response(urine_volume, date_time_str, remarks, result)

    except requests.exceptions.ConnectionError as e:
        logger.bind(tag=TAG).error(f"连接尿量上报API失败: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="网络连接失败，暂时无法上报尿量数据，请稍后再试",
        )

    except requests.exceptions.Timeout as e:
        logger.bind(tag=TAG).error(f"尿量上报API请求超时: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="尿量数据上报超时，请稍后再试",
        )

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if hasattr(e, "response") else "未知"
        error_detail = ""
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = e.response.text if hasattr(e, "response") else ""
        logger.bind(tag=TAG).error(
            f"尿量上报API返回错误, 状态码: {status_code}, 详情: {error_detail}"
        )
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="尿量数据上报服务异常，请稍后再试或联系管理员",
        )

    except Exception as e:
        logger.bind(tag=TAG).error(f"尿量数据上报发生未知异常: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="尿量数据上报失败，请稍后再试",
        )


def _handle_mock_response(conn, urine_volume, date_time_str, remarks):
    """处理mock响应，模拟外部API返回"""
    import uuid
    from datetime import timedelta

    mock_record_id = f"urine_volume-{uuid.uuid4().hex[:12].upper()}"
    mock_patient_name = f"用户{conn.device_id[-4:]}" if conn.device_id else "未知用户"

    mock_result = {
        "code": 0,
        "message": "success",
        "id": mock_record_id,
        "record_id": mock_record_id,
        "patient_id": conn.device_id,
        "patient_name": mock_patient_name,
        "value": urine_volume,
        "remarks": remarks or "",
        "unit": "kg",
        "status": "confirmed",
        "created_at": date_time_str,
        "next_measure_reminder": (
            datetime.now() + timedelta(days=1)
        ).strftime("%Y-%m-%d %H:%M:%S"),
    }

    logger.bind(tag=TAG).info(
        f"【Mock】尿量数据上报模拟成功, mock响应: {mock_result}"
    )

    return _build_success_response(urine_volume, date_time_str, remarks, mock_result)


def _build_success_response(urine_volume, date_time_str, remarks, api_result):
    """构建上报成功后的LLM结果文本"""
    result_text = (
        f"用户尿量数据已成功上报。\n"
        f"尿量: {urine_volume}公斤\n"
        f"上报时间: {date_time_str}\n"
    )
    if remarks:
        result_text += f"备注: {remarks}\n"

    if isinstance(api_result, dict):
        record_id = api_result.get("id") or api_result.get("record_id")
        if record_id:
            result_text += f"记录ID: {record_id}\n"

    result_text += "\n请告知用户尿量数据已记录成功，并给予鼓励。"

    return ActionResponse(
        action=Action.REQLLM,
        result=result_text,
        response=None,
    )

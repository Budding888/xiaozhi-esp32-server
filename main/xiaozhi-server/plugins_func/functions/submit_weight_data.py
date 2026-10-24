"""
体重数据上报插件
用户通过语音上报体重数据，调用外部系统的体重更新API接口完成数据记录
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

PLUGIN_NAME = "submit_weight_data"


def _get_effective_plugin_config(conn: "ConnectionHandler") -> dict:
    """获取插件配置。

    运行时配置（智控台下放）优先；但智控台常只配置了部分字段（如仅 url，缺少 api_key）。
    缺失的 api_url/api_key 回退到本地 config.yaml 中的插件配置，避免命中默认占位地址
    （https://rpm.com/api/submitWeight）导致上报失败。
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
    # 运行时（智控台）配置覆盖本地配置，保证智控台仍拥有最高优先级
    merged.update(effective)
    return merged

submit_weight_data_function_desc = {
    "type": "function",
    "function": {
        "name": "submit_weight_data",
        "description": (
            "用于用户上报体重数据。"
            "当用户说'我要上报体重数据，今天的体重是XX公斤'、'今天的体重是XX公斤，请上报体重数据'、'今天的体重是XX公斤，请上报'、'我要上报体重，体重是XX公斤'等与体重记录与上报相关的指令时调用此功能。"
            "注意：1.如果用户说的体重单位是斤或磅，需转换为公斤后再上报。如果用户说的体重没有单位，单位就默认公斤。2.上报、提交、登记、上传、报上去、提交一下、上报一下、帮我提交、帮我上报、反馈一下、记录、录入、保存、记下来、存一下、帮我记下、录入进去、保存一下等均是同义词。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "weight": {
                    "type": "number",
                    "description": "体重数值，单位为公斤(kg)。例如：65.5表示65.5公斤。如果用户说的是斤，需要除以2转换为公斤；如果是磅，需要乘以0.4536转换为公斤",
                },
                "remarks": {
                    "type": "string",
                    "description": "备注信息，例如'饭后测量'、'早晨空腹'、'睡前测量'、'上机前'、'下机后'、'早上'、'中午'、'下午'、'晚上'等",
                },
            },
            "required": ["weight"],
        },
    },
}


@register_function("submit_weight_data", submit_weight_data_function_desc, ToolType.SYSTEM_CTL)
def submit_weight_data( conn: "ConnectionHandler", weight: float, remarks: str = None):
    """
    上报用户体重数据到外部健康管理系统

    Args:
        conn: 连接处理器，用于获取配置和设备信息
        weight: 体重值（公斤），必填
        remarks: 备注信息，可选
    """
    logger.bind(tag=TAG).info(
        f"收到体重上报请求: weight={weight},  remarks={remarks}"
    )

    if not weight:
        logger.bind(tag=TAG).info("体重未上报，请检查后重新上报")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="您上报的体重数据上报不完整，体重数值未上报，请检查后重新上报"
        )

    # 参数校验
    if weight <= 0 or weight > 500:
        logger.bind(tag=TAG).info(f"体重数值异常: {weight}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response=f"您上报的体重数值{weight}公斤看起来不太合理，请确认后重新上报",
        )

    # 读取插件配置：运行时(智控台)配置优先，缺失字段回退到本地 config.yaml
    plugin_config = _get_effective_plugin_config(conn)
    if not plugin_config:
        logger.bind(tag=TAG).info("插件配置参数未配置，请检查")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="插件配置参数未配置，请联系管理员完善设置"
        )

    # 兼容智控台中配置为 url 而非 api_url 的情况
    api_url = plugin_config.get("api_url") or plugin_config.get("url")
    api_key = plugin_config.get("api_key")
    timeout = plugin_config.get("timeout", 20)
    use_mock = plugin_config.get("use_mock", False)


    if not api_url:
        logger.bind(tag=TAG).info("体重上报API地址未正确配置，请检查")
        return ActionResponse(
            action=Action.RESPONSE, result=None,

            response="体重数据上报API地址暂未配置，请联系管理员完善设置"
        )

    # 构建请求数据
    now = datetime.now()
    date_time_str=now.strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "deviceId": conn.device_id,
        "clientId": conn.client_id,
        "value": weight,
        "remarks": remarks or "",
        "type": "submit_weight_data",
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
    if use_mock==True:
        return _handle_mock_response(conn, weight, date_time_str, remarks)

    logger.bind(tag=TAG).info(
        f"正在上报体重数据到外部API: {api_url}, payload: {payload}"
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
        logger.bind(tag=TAG).info(f"体重数据上报成功, API响应: {result}")
        return build_success_response(weight, date_time_str, remarks, result)

    except requests.exceptions.ConnectionError as e:
        logger.bind(tag=TAG).error(f"连接体重上报API失败: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="网络连接失败，暂时无法上报体重数据，请稍后再试",
        )

    except requests.exceptions.Timeout as e:
        logger.bind(tag=TAG).error(f"体重上报API请求超时: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="体重数据上报超时，请稍后再试",
        )

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if hasattr(e, "response") else "未知"
        error_detail = ""
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = e.response.text if hasattr(e, "response") else ""
        logger.bind(tag=TAG).error(
            f"体重上报API返回错误, 状态码: {status_code}, 详情: {error_detail}"
        )
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="体重数据上报服务异常，请稍后再试或联系管理员",
        )

    except Exception as e:
        logger.bind(tag=TAG).error(f"体重数据上报发生未知异常: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="体重数据上报失败，请稍后再试",
        )


"""处理mock响应，模拟外部API返回"""
def _handle_mock_response(conn, weight, date_time_str, remarks):

    import uuid
    from datetime import timedelta

    mock_record_id = f"WEIGHT-{uuid.uuid4().hex[:12].upper()}"
    mock_patient_name = f"用户{conn.device_id[-4:]}" if conn.device_id else "未知用户"

    mock_result = {
        "code": 0,
        "message": "success",
        "id": mock_record_id,
        "record_id": mock_record_id,
        "patient_id": conn.device_id,
        "patient_name": mock_patient_name,
        "value": weight,
        "remarks": remarks or "",
        "unit": "kg",
        "status": "confirmed",
        "created_at": date_time_str,
        "next_measure_reminder": (
            datetime.now() + timedelta(days=1)
        ).strftime("%Y-%m-%d %H:%M:%S"),
    }

    logger.bind(tag=TAG).info(
        f"【Mock】体重数据上报模拟成功, mock响应: {mock_result}"
    )

    return build_success_response(weight, date_time_str, remarks, mock_result)


def build_success_response(weight, date_time_str, remarks, api_result):
    """构建上报成功后的LLM结果文本"""
    result_text = (
        f"用户体重数据已成功上报。\n"
        f"体重: {weight}公斤\n"
        f"上报时间: {date_time_str}\n"
    )
    if remarks:
        result_text += f"备注: {remarks}\n"

    if isinstance(api_result, dict):
        record_id = api_result.get("id") or api_result.get("record_id")
        if record_id:
            result_text += f"记录ID: {record_id}\n"

    result_text += "\n请告知用户体重数据已记录成功，并给予鼓励。"

    logger.bind(tag=TAG).info(
        f"体重数据上报成功, result_text响应: {result_text}"
    )
    return ActionResponse(
        action=Action.REQLLM,
        result=result_text,
        response=None,
    )

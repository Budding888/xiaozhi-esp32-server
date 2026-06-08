"""
用药状态更新插件
用户通过语音上报服药状态，调用外部系统的用药状态更新API接口完成数据记录
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

update_medication_reminder_status_function_desc = {
    "type": "function",
    "function": {
        "name": "update_medication_reminder_status",
        "description": (
            "用于更新用户的服药状态。"
            "当用户说'早上我吃了卡维地洛片, 请上报'、'中午已经服用了XXX药, 请上报'、'下午还没吃药, 请上报'、'早上的药已经吃了'等与用药状态更新相关的指令时调用此功能。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "medication_period": {
                    "type": "string",
                    "description": "服药时间段，例如：'早上'、'中午'、'下午'、'晚上'、'睡前'等",
                },
                "medicine_name": {
                    "type": "string",
                    "description": "药品名称，例如：'卡维地洛片'、'阿司匹林'、'二甲双胍'等",
                },
                "medication_status": {
                    "type": "string",
                    "description": "服药状态，取值为'已服药'或'未服药'",
                },
            },
            "required": ["medication_period", "medicine_name", "medication_status"],
        },
    },
}


@register_function("update_medication_reminder_status", update_medication_reminder_status_function_desc, ToolType.SYSTEM_CTL)
def update_medication_reminder_status(
    conn: "ConnectionHandler",
    medication_period: str,
    medicine_name: str,
    medication_status: str,
):
    """
    更新用户用药提醒状态到外部健康管理系统

    Args:
        conn: 连接处理器，用于获取配置和设备信息
        medication_period: 服药时间段（早上、中午、下午、晚上、睡前等），必填
        medicine_name: 药品名称，必填
        medication_status: 服药状态（已服药/未服药），必填
    """
    logger.bind(tag=TAG).info(
        f"收到用药状态更新请求: medication_period={medication_period}, "
        f"medicine_name={medicine_name}, medication_status={medication_status}"
    )

    # 参数校验
    valid_periods = ["早上", "中午", "晚上"]
    if medication_period not in valid_periods:
        logger.bind(tag=TAG).info(f"服药时间段无效: {medication_period}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response=f"您说的时间段'{medication_period}'我不太理解，请确认是早上、中午还是晚上",
        )

    if not medicine_name or not medicine_name.strip():
        logger.bind(tag=TAG).info("药品名称为空")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="请告诉我药品名称，例如'卡维地洛片'或'阿司匹林'",
        )

    valid_statuses = ["已服药", "未服药"]
    if medication_status not in valid_statuses:
        logger.bind(tag=TAG).info(f"服药状态无效: {medication_status}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="请确认服药状态是'已服药'还是'未服药'",
        )

    # 从config.yaml文件的插件配置中读取外部API信息
    logger.bind(tag=TAG).info(f"-----------conn.config.get(plugins)----------：{conn.config.get('plugins', {})}")
    plugin_config = conn.config.get("plugins", {}).get("update_medication_reminder_status", {})
    if not plugin_config:
        logger.bind(tag=TAG).info("插件配置参数未配置，请检查")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="插件配置参数未配置，请联系管理员完善设置"
        )
    api_url = plugin_config.get("api_url", "https://rpm.com/api/update_medication_status")
    api_key = plugin_config.get("api_key", "XXX")
    timeout = plugin_config.get("timeout", 20)
    use_mock = plugin_config.get("use_mock", False)
    logger.bind(tag=TAG).info(f"-----------plugin_config----------：{plugin_config}")



    if not api_url:
        logger.bind(tag=TAG).info("用药状态更新API地址未正确配置，请检查")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="用药状态更新API地址暂未配置，请联系管理员完善设置"
        )
    if not api_key:
        logger.bind(tag=TAG).info("用药状态更新API key未正确配置，请检查")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="用药状态更新API key暂未配置，请联系管理员完善设置"
        )

    # 构建请求数据
    now = datetime.now()
    date_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "device_id": conn.device_id,
        "patient_id": conn.device_id,
        "medication_period": medication_period,
        "medicine_name": medicine_name,
        "medication_status": medication_status,
        "type": "update_medication_reminder_status",
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
        return _handle_mock_response(conn, medication_period, medicine_name, medication_status, date_time_str)

    logger.bind(tag=TAG).info(
        f"正在更新用药状态到外部API: {api_url}, payload: {payload}"
    )

    try:
        # response = requests.post(
        #    api_url,
        #    json=payload,
        #    headers=headers,
        #     timeout=timeout,
        # )

        # 构造一个测试数据：404响应对象
        # response = MockErrorResponse()
        response = MockSuccessResponse()


        # 校验响应的状态，存在错误码，则返回错误信息
        response.raise_for_status()

        # 处理响应成功时返回信息
        result = response.json()
        logger.bind(tag=TAG).info(f"用药状态更新成功, API响应: {result}")

        return _build_success_response(medication_period, medicine_name, medication_status, date_time_str, result)

    except requests.exceptions.ConnectionError as e:
        logger.bind(tag=TAG).error(f"连接用药状态更新API失败: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="网络连接失败，暂时无法更新用药状态，请稍后再试",
        )

    except requests.exceptions.Timeout as e:
        logger.bind(tag=TAG).error(f"用药状态更新API请求超时: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="用药状态更新超时，请稍后再试",
        )

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if hasattr(e, "response") else "未知"
        error_detail = ""
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = e.response.text if hasattr(e, "response") else ""
        logger.bind(tag=TAG).error(
            f"用药状态更新API返回错误, 状态码: {status_code}, 详情: {error_detail}"
        )
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="用药状态更新服务异常，请稍后再试或联系管理员",
        )

    except Exception as e:
        logger.bind(tag=TAG).error(f"用药状态更新发生未知异常: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="用药状态更新失败，请稍后再试",
        )


# 模拟 200 成功响应
class MockSuccessResponse:
    def __init__(self, url=""):
        self.status_code = 200
        self.reason = "OK"
        self.url = url
        self.text = '{"code":200,"message":"服药状态上报成功"}'
        self.content = self.text.encode("utf-8")
        self.headers = {}
        self.encoding = "utf-8"

    def json(self):
        return {"code": 200, "message": "服药状态上报成功"}

    def raise_for_status(self):
        # 200 不抛异常，符合 requests 原生行为
        pass

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
        f"【Mock】服药状态模拟成功, mock响应: {mock_result}"
    )

    return _handle_mock_response(weight, date_time_str, remarks, mock_result)



def _handle_mock_response(conn, medication_period, medicine_name, medication_status, date_time_str):
    """处理mock响应，模拟外部API返回"""
    import uuid
    from datetime import timedelta

    mock_record_id = f"medication-{uuid.uuid4().hex[:12].upper()}"
    mock_patient_name = f"用户{conn.device_id[-4:]}" if conn.device_id else "未知用户"

    mock_result = {
        "code": 0,
        "message": "success",
        "id": mock_record_id,
        "record_id": mock_record_id,
        "patient_id": conn.device_id,
        "patient_name": mock_patient_name,
        "medication_period": medication_period,
        "medicine_name": medicine_name,
        "medication_status": medication_status,
        "status": "confirmed",
        "created_at": date_time_str,
        "next_medication_reminder": (
            datetime.now() + timedelta(hours=12)
        ).strftime("%Y-%m-%d %H:%M:%S"),
    }

    logger.bind(tag=TAG).info(
        f"【Mock】用药状态更新模拟成功, mock响应: {mock_result}"
    )

    return _build_success_response(medication_period, medicine_name, medication_status, date_time_str, mock_result)


def _build_success_response(medication_period, medicine_name, medication_status, date_time_str, api_result):
    """构建更新成功后的LLM结果文本"""
    status_text = "已服用" if medication_status == "已服药" else "未服用"
    result_text = (
        f"用户用药状态已成功更新。\n"
        f"用药时间: {medication_period}\n"
        f"药品名称: {medicine_name}\n"
        f"服药状态: {status_text}\n"
        f"上报时间: {date_time_str}\n"
    )

    if isinstance(api_result, dict):
        record_id = api_result.get("id") or api_result.get("record_id")
        if record_id:
            result_text += f"记录ID: {record_id}\n"

    result_text += "\n请告知用户用药状态已记录成功，并给予鼓励。"

    return ActionResponse(
        action=Action.REQLLM,
        result=result_text,
        response=None,
    )

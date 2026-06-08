"""
血压数据上报插件
用户通过语音上报血压数据，调用外部系统的血压更新API接口完成数据记录
"""
from datetime import datetime
from http.client import HTTPResponse

import requests
from aiohttp.web_exceptions import HTTPSuccessful

from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

submit_blood_pressure_data_function_desc = {
    "type": "function",
    "function": {
        "name": "submit_blood_pressure_data",
        "description": (
            "用于用户上报血压数据"
            "用户者说'我要上报血压数据，今天的高压是150、低压是120'、'下机后高压是150、低压是120，请上报血压数据'、'上机前收缩压是150、舒张压是120，请上报'、'我要上报血压，下午血压是150、120'、'我要上报血压，血压是150/120'、'我要上报血压，血压是150和120'、'高压150，低压120，请上报'、'收缩压150，舒张压120，请上报'等与血压记录与上报相关的指令时调用此功能。"
            "注意：如果用户说的血压没有明确高压与低压时，将数值大的识别为高压/收缩压/上压，数值小识别为低压/舒张压/下压。"
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

    # 从config.yaml文件的插件配置中读取外部API信息
    plugin_config = conn.config.get("plugins", {}).get("submit_blood_pressure_data", {})
    api_url = plugin_config.get("api_url", "https://rpm.com/api/submitWeight")
    api_key = plugin_config.get("api_key", "XXX")
    timeout = plugin_config.get("timeout", 20)

    if not plugin_config:
        logger.bind(tag=TAG).info("插件配置参数未配置，请检查")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="插件配置参数未配置，请联系管理员完善设置"
        )
    if not api_url:
        logger.bind(tag=TAG).info("血压上报API地址未正确配置，请检查")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="血压数据上报API地址暂未配置，请联系管理员完善设置"
        )
    if not api_key:
        logger.bind(tag=TAG).info("血压上报API key未正确配置，请检查")
        return ActionResponse(
            action=Action.RESPONSE, result=None,
            response="血压数据上报API key暂未配置，请联系管理员完善设置"
        )

    # 构建请求数据
    now = datetime.now()
    date_time_str=now.strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "device_id": conn.device_id,
        "patient_id": conn.device_id,
        "sbp_value": systolic,
        "dbp_value": diastolic,
        "remarks": remarks or "",
        "type": "submit_blood_pressure_data",
        "source": "xiaozhi_voice_assistant",
        "timestamp": date_time_str,
    }

    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    logger.bind(tag=TAG).info(
        f"正在上报血压数据到外部API: {api_url}, payload: {payload}"
    )

    try:
        # TODO:待完善
        # response = requests.post(
        #    api_url,
        #    json=payload,
        #     headers=headers,
        #     timeout=timeout,
        # )

        # 构造一个测试数据：404响应对象
        # response = MockErrorResponse()
        response = MockSuccessResponse()

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


from requests.exceptions import HTTPError

# 模拟 404 错误响应
class MockErrorResponse:
    def __init__(self, status_code=404, reason="Not Found", url=""):
        self.status_code = status_code
        self.reason = reason
        self.url = url
        self.text = f"{status_code} {reason}"
        self.content = self.text.encode("utf-8")
        self.headers = {}
        self.encoding = "utf-8"

    def json(self):
        return {"error": self.reason, "code": self.status_code}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPError(
                f"{self.status_code} Client Error: {self.reason} for url: {self.url}",
                response=self
            )

# 模拟 200 成功响应
class MockSuccessResponse:
    def __init__(self, url=""):
        self.status_code = 200
        self.reason = "OK"
        self.url = url
        self.text = '{"code":200,"message":"血压数据上报成功"}'
        self.content = self.text.encode("utf-8")
        self.headers = {}
        self.encoding = "utf-8"

    def json(self):
        return {"code": 200, "message": "血压数据上报成功"}

    def raise_for_status(self):
        # 200 不抛异常，符合 requests 原生行为
        pass


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

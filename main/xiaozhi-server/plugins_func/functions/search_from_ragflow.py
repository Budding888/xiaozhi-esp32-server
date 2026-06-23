import requests
import sys
import time
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

# 定义基础的函数描述模板
SEARCH_FROM_RAGFLOW_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "search_from_ragflow",
        "description": "从知识库中查询信息",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "查询的问题"}},
            "required": ["question"],
        },
    },
}



def _call_ragflow_with_retry(url, headers, payload, timeout, max_retries=2, retry_delay=1.0):
    """
    带重试机制的 RAGFlow API 调用

    对网络异常（ConnectTimeout、ConnectionError、Timeout）和 HTTP 5xx 自动重试，
    HTTP 4xx、业务错误码等不重试，直接抛出异常。

    Args:
        url: API 地址
        headers: 请求头
        payload: 请求体
        timeout: 超时设置（int 或 tuple(connect, read)）
        max_retries: 最大重试次数（默认 2，不含首次尝试）
        retry_delay: 重试间隔基准秒数（指数退避，第 n 次 = retry_delay × 2^(n-1)）

    Returns:
        requests.Response: 成功响应对象

    Raises:
        requests.exceptions.RequestException: 所有重试耗尽后抛出最后一次异常


    Code	Message	Description
    400	    Bad Request	Invalid request parameters
    401	    Unauthorized	Unauthorized access
    403	    Forbidden	Access denied
    404	    Not Found	Resource not found
    500	    Internal Server Error	Server internal error
    1001	Invalid Chunk ID	Invalid Chunk ID
    1002	Chunk Update Failed	Chunk update failed
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                wait_time = retry_delay * (2 ** (attempt - 1))
                logger.bind(tag=TAG).warning(
                    f"RAGFlow API 请求失败，第 {attempt}/{max_retries} 次重试，等待 {wait_time:.1f}s"
                )
                time.sleep(wait_time)

            response = requests.post(
                url=url,
                json=payload,
                headers=headers,
                timeout=timeout,
                verify=False,
            )

            # HTTP 4xx 触发重试
            if response.status_code >= 400:
                logger.bind(tag=TAG).warning(
                    f"RAGFlow API 返回 {response.status_code}，触发重试"
                )
                response.raise_for_status()  # 抛出 HTTPError

            # HTTP 4xx 或 2xx
            response.raise_for_status()
            return response  # 成功

        except requests.exceptions.HTTPError as e:
            last_exception = e
            # HTTP 4xx 不重试，直接抛出
            if e.response is not None and 400 <= e.response.status_code < 500:
                raise
            # 5xx 继续循环重试

        except requests.exceptions.RequestException as e:
            last_exception = e
            # 网络异常（超时、连接错误等），继续循环重试

    # 所有重试耗尽
    logger.bind(tag=TAG).error(
        f"RAGFlow API 请求重试 {max_retries} 次后仍然失败: {type(last_exception).__name__}: {last_exception}"
    )
    raise last_exception


@register_function(
    "search_from_ragflow", SEARCH_FROM_RAGFLOW_FUNCTION_DESC, ToolType.SYSTEM_CTL
)
def search_from_ragflow(conn: "ConnectionHandler", question=None):
    # 确保字符串参数正确处理编码
    if question and isinstance(question, str):
        # 确保问题参数是UTF-8编码的字符串
        pass
    else:
        question = str(question) if question is not None else ""

    ragflow_config = conn.config.get("plugins", {}).get("search_from_ragflow", {})
    base_url = ragflow_config.get("base_url", "")
    api_key = ragflow_config.get("api_key", "")
    dataset_ids = ragflow_config.get("dataset_ids", [])
    # 读取检索参数
    top_k = ragflow_config.get("top_k", 100)
    similarity_threshold = ragflow_config.get("similarity_threshold", 0.25)
    vector_similarity_weight = ragflow_config.get("vector_similarity_weight", 0.4)
    # 读取配置：8s建立连接，25s读取完整响应
    req_timeout = ragflow_config.get("request_timeout", (10, 50))

    url = base_url + "/api/v1/retrieval"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # 确保payload中的字符串都是UTF-8编码
    payload = {
        "question": question,
        "dataset_ids": dataset_ids,
        "top_k": top_k,
        "similarity_threshold": similarity_threshold,
        "vector_similarity_weight": vector_similarity_weight,
        "keyword": True,
    }

    try:
        # 使用带重试机制的 API 调用（网络异常和 5xx 自动重试 2 次）
        response = _call_ragflow_with_retry(url, headers, payload, req_timeout)

        # 显式设置响应的编码为utf-8
        response.encoding = "utf-8"

        response.raise_for_status()

        # 先获取文本内容，然后手动处理JSON解码
        response_text = response.text
        import json

        result = json.loads(response_text)

        if result.get("code") != 0:
            error_detail = result.get("error", {}).get("detail", "未知错误")
            error_message = result.get("error", {}).get("message", "")
            error_code = result.get("code", "")

            # 安全地记录错误信息
            logger.bind(tag=TAG).error(
                f"RAGFlow API调用失败，响应码：{error_code}，错误详情：{error_detail}，完整响应：{result}"
            )

            # 构建详细的错误响应
            error_response = f"RAG接口返回异常（错误码：{error_code}）"

            if error_message:
                error_response += f"：{error_message}"
            if error_detail:
                error_response += f"\n详情：{error_detail}"

            return ActionResponse(Action.RESPONSE, None, error_response)

        chunks = result.get("data", {}).get("chunks", [])
        contents = []
        for chunk in chunks:
            content = chunk.get("content", "")
            if content:
                # 安全地处理内容字符串
                if isinstance(content, str):
                    contents.append(content)
                elif isinstance(content, bytes):
                    contents.append(content.decode("utf-8", errors="replace"))
                else:
                    contents.append(str(content))

        if contents:
            # 组织知识库内容为引用模式
            context_text = f"# 关于问题【{question}】查到知识库如下\n"
            context_text += "```\n\n\n".join(contents[:5])
            context_text += "\n```"
        else:
            context_text = "根据知识库查询结果，没有相关信息。"
        return ActionResponse(Action.REQLLM, context_text, None)

    except requests.exceptions.RequestException as e:
        # 网络请求异常
        error_type = type(e).__name__
        logger.bind(tag=TAG).error(
            f"RAGflow网络请求失败，异常类型：{error_type}，详情：{str(e)}"
        )

        # 根据异常类型提供更详细的错误信息和解决方案
        if isinstance(e, requests.exceptions.ConnectTimeout):
            error_response = "RAG接口连接超时（5秒）"
            error_response += "\n可能原因：RAGflow服务未启动或网络连接问题"
            error_response += "\n解决方案：请检查RAGflow服务状态和网络连接"

        elif isinstance(e, requests.exceptions.ConnectionError):
            error_response = "无法连接到RAG接口"
            error_response += "\n可能原因：RAGflow服务地址错误或服务未运行"
            error_response += "\n解决方案：请检查RAGflow服务地址配置和服务状态"

        elif isinstance(e, requests.exceptions.Timeout):
            error_response = "RAG接口请求超时"
            error_response += "\n可能原因：RAGflow服务响应缓慢或网络延迟"
            error_response += "\n解决方案：请稍后重试或检查RAGflow服务性能"

        elif isinstance(e, requests.exceptions.HTTPError):
            # 处理HTTP错误状态码
            if hasattr(e.response, "status_code"):
                status_code = e.response.status_code
                error_response = f"RAG接口HTTP错误（状态码：{status_code}）"

                # 尝试获取响应内容中的错误信息
                try:
                    error_detail = e.response.json().get("error", {}).get("message", "")
                    if error_detail:
                        error_response += f"\n错误详情：{error_detail}"
                except:
                    pass
            else:
                error_response = f"RAG接口HTTP异常：{str(e)}"

        else:
            error_response = f"RAG接口网络异常（{error_type}）：{str(e)}"

        return ActionResponse(Action.RESPONSE, None, error_response)

    except Exception as e:
        # 其他异常
        error_type = type(e).__name__
        logger.bind(tag=TAG).error(
            f"RAGflow处理异常，异常类型：{error_type}，详情：{str(e)}"
        )

        # 提供详细的错误信息
        error_response = f"RAG接口处理异常（{error_type}）：{str(e)}"
        return ActionResponse(Action.RESPONSE, None, error_response)








@register_function(
    "search_from_ragflow_v2", SEARCH_FROM_RAGFLOW_FUNCTION_DESC, ToolType.SYSTEM_CTL
)
def search_from_ragflow_v2(conn: "ConnectionHandler", question=None):
    logger.bind(tag=TAG).info(f"===========触发知识库问答(search_from_ragflow_v2)===========，问题: {question}")
    # 确保字符串参数正确处理编码
    if question and isinstance(question, str):
        # 确保问题参数是UTF-8编码的字符串
        pass
    else:
        question = str(question) if question is not None else ""

    ragflow_config = conn.config.get("plugins", {}).get("search_from_ragflow", {})
    base_url = ragflow_config.get("base_url", "")
    api_key = ragflow_config.get("api_key", "")
    dataset_ids = ragflow_config.get("dataset_ids", [])
    # 读取检索参数
    top_k = ragflow_config.get("top_k", 100)
    similarity_threshold = ragflow_config.get("similarity_threshold", 0.25)
    vector_similarity_weight = ragflow_config.get("vector_similarity_weight", 0.4)
    # 读取配置：8s建立连接，25s读取完整响应
    req_timeout = ragflow_config.get("request_timeout", (10, 50))

    # 调用RagFlow知识库的教唆接口
    url = base_url + "/api/v1/retrieval"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # 确保payload中的字符串都是UTF-8编码
    payload = {
        "question": question,
        "dataset_ids": dataset_ids,
        "top_k": top_k,
        "similarity_threshold": similarity_threshold,
        "vector_similarity_weight": vector_similarity_weight,
        "keyword": True,
    }

    try:
        # 使用带重试机制的 API 调用（网络异常和 5xx 自动重试 2 次）
        response = _call_ragflow_with_retry(url, headers, payload, req_timeout)
        # 显式设置响应的编码为utf-8
        response.encoding = "utf-8"
        # 先获取文本内容，然后手动处理JSON解码
        response_text = response.text

        import json
        result = json.loads(response_text)
        logger.bind(tag=TAG).info(f"===========RAGFlow API调用成功，返回的原始结果===========：{result}")

        if result.get("code") != 0:
            error_detail = result.get("error", {}).get("detail", "未知错误")
            error_message = result.get("error", {}).get("message", "")
            error_code = result.get("code", "")

            # 记录错误信息
            logger.bind(tag=TAG).error( f"RAGFlow API调用失败，响应码：{error_code}，错误详情：{error_detail}，完整响应：{result}")

            # 构建详细的错误响应
            error_response = f"RAG接口返回异常（错误码：{error_code}）"

            if error_message:
                error_response += f"：{error_message}"
            if error_detail:
                error_response += f"\n详情：{error_detail}"

            return ActionResponse(Action.RESPONSE, None, error_response)

        chunks = result.get("data", {}).get("chunks", [])
        # logger.bind(tag=TAG).info(f"===========RAGFlow检索到的chunks===========：{chunks}")
        contents = []

        # 按相似度得分排序、过滤低相关度chunk
        scored_chunks = []
        for chunk in chunks:
            content = chunk.get("content", "")
            if not content:
                continue
            # 安全地处理内容字符串
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
            elif not isinstance(content, str):
                content = str(content)

            similarity = chunk.get("similarity", chunk.get("score", 1.0))
            scored_chunks.append((similarity, content))

        # 按相似度降序排列（最相关在前）
        scored_chunks.sort(key=lambda x: float(x[0]), reverse=True)

        # 过滤低相关度chunk，并记录日志
        before_count = len(scored_chunks)
        scored_chunks = [
            (score, text) for score, text in scored_chunks
            if score >= similarity_threshold
        ]
        after_count = len(scored_chunks)

        if before_count != after_count:
            logger.bind(tag=TAG).info( f"相似度阈值过滤: {before_count} -> {after_count} 个chunk " f"(阈值={similarity_threshold})")

        if after_count == 0 and before_count > 0:
            logger.bind(tag=TAG).warning(
                f"所有chunk均低于相似度阈值({similarity_threshold})，"
                f"将返回空结果让医疗Qwen基于自身知识回答"
            )

        for score, content in scored_chunks:
            logger.bind(tag=TAG).debug( f"chunk相似度={score:.4f}, 内容前40字: {content[:40]}..." )
            contents.append(content)

        if contents:
            context_text = f"# 关于问题【{question}】知识库的检索结果如下\n"
            context_text += "```\n\n\n".join(contents)
            context_text += "\n```"
        else:
            context_text = "根据知识库查询结果，没有相关信息。"
        return ActionResponse(Action.REQLLM, context_text, None)

    except requests.exceptions.RequestException as e:
        # 网络请求异常
        error_type = type(e).__name__
        logger.bind(tag=TAG).error(f"RAGflow网络请求失败，异常类型：{error_type}，详情：{str(e)}")

        # 根据异常类型提供更详细的错误信息和解决方案
        if isinstance(e, requests.exceptions.ConnectTimeout):
            error_response = "RAG接口连接超时（10秒）"
            error_response += "\n可能原因：RAGflow服务未启动或网络连接问题"
            error_response += "\n解决方案：请检查RAGflow服务状态和网络连接"

        elif isinstance(e, requests.exceptions.ConnectionError):
            error_response = "无法连接到RAG接口"
            error_response += "\n可能原因：RAGflow服务地址错误或服务未运行"
            error_response += "\n解决方案：请检查RAGflow服务地址配置和服务状态"

        elif isinstance(e, requests.exceptions.Timeout):
            error_response = "RAG接口请求超时"
            error_response += "\n可能原因：RAGflow服务响应缓慢或网络延迟"
            error_response += "\n解决方案：请稍后重试或检查RAGflow服务性能"

        elif isinstance(e, requests.exceptions.HTTPError):
            # 处理HTTP错误状态码
            if hasattr(e.response, "status_code"):
                status_code = e.response.status_code
                error_response = f"RAG接口HTTP错误（状态码：{status_code}）"

                # 尝试获取响应内容中的错误信息
                try:
                    error_detail = e.response.json().get("error", {}).get("message", "")
                    if error_detail:
                        error_response += f"\n错误详情：{error_detail}"
                except:
                    pass
            else:
                error_response = f"RAG接口HTTP异常：{str(e)}"

        else:
            error_response = f"RAG接口网络异常（{error_type}）：{str(e)}"

        return ActionResponse(Action.RESPONSE, None, error_response)

    except Exception as e:
        # 其他异常
        error_type = type(e).__name__
        logger.bind(tag=TAG).error(
            f"RAGflow处理异常，异常类型：{error_type}，详情：{str(e)}"
        )

        # 提供详细的错误信息
        error_response = f"RAG接口处理异常（{error_type}）：{str(e)}"
        return ActionResponse(Action.RESPONSE, None, error_response)


# ============================================================
# search_from_ragflow_chat — 基于 RAGFlow Chat API 的一站式检索+问答
# 参考 test/ragflow_chat_test.py
# 直接调用 RAGFlow 内置的 /api/v1/chat/completions 接口，
# 由 RAGFlow 自行完成知识库检索 + LLM 推理，返回完整答案。
# 不再需要外部 MedicalQwen 参与。
# ============================================================

SEARCH_FROM_RAGFLOW_CHAT_DESC = {
    "type": "function",
    "function": {
        "name": "search_from_ragflow_chat",
        "description": "从医疗知识库中查询腹透相关问题的答案，RAGFlow 自行检索知识库并生成回答",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "查询的问题"}
            },
            "required": ["question"]
        }
    }
}


@register_function(
    "search_from_ragflow_chat", SEARCH_FROM_RAGFLOW_CHAT_DESC, ToolType.SYSTEM_CTL
)
def search_from_ragflow_chat(conn: "ConnectionHandler", question=None, stream=True, pass_all_history_messages=True):
    """
    一站式知识库问答（RAGFlow Chat API）

    直接调用 RAGFlow 的 /api/v1/chat/completions 接口，
    RAGFlow 自行完成：知识库检索 → LLM 推理 → 生成答案。
    无需再调用外部 MedicalQwen。

    流式模式会将逐 chunk 的答案实时送入 TTS 队列，
    非流式模式返回完整回答文本。

    Args:
        conn: 连接处理器
        question: 查询问题
        stream: 是否启用流式输出（默认 True，流式输出到 TTS）

    Returns:
        ActionResponse: REQLLM（含回答文本）或 RESPONSE（错误信息）
    """
    logger.bind(tag=TAG).info(f"===========触发知识库问答(search_from_ragflow_chat)===========，问题: {question}")

    if not question:
        return ActionResponse(Action.RESPONSE, None, "请提供查询问题")

    # 读取配置
    ragflow_config = conn.config.get("plugins", {}).get("search_from_ragflow", {})
    base_url = ragflow_config.get("base_url", "")
    api_key = ragflow_config.get("api_key", "")
    chat_system_prompt = ragflow_config.get(
        "chat_system_prompt",
        "你是医疗知识库专属问答助手，请总结知识库的内容来回答问题，列举知识库中的数据详细回答。当所有知识库内容都与问题无关时，使用自身专业知识解答问题，需要注意：不做诊断、不开处方，术语严谨、逻辑清晰，全程保持医学术语准确、逻辑清晰，语言客观中立，仅做健康知识科普。"
    )

    if not base_url or not api_key:
        logger.bind(tag=TAG).error("RAGFlow Chat 配置不完整：缺少 base_url 或 api_key")
        return ActionResponse(
            Action.RESPONSE, None, "知识库服务配置不完整，请联系管理员"
        )

    url = base_url + "/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

        # "pass_all_history_messages": true,  # 是否传递全部历史对话消息
    payload = {
        "question": question,
        "messages": [
            {"role": "system", "content": chat_system_prompt},
            {"role": "user", "content": question},
        ],
        "stream": stream,
        "pass_all_history_messages": False
    }

    try:
        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            stream=stream,
            timeout=30,
            verify=False,
        )
        # 打印请求结果
        logger.bind(tag=TAG).debug(f"===========RAGFlow检索结果===========：{resp.text}")

        resp.encoding = "utf-8"
        resp.raise_for_status()

        full_answer = ""

        if stream:
            import json

            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                if raw_line.startswith("data:"):
                    json_str = raw_line[5:].strip()
                    if not json_str:
                        continue
                    try:
                        data = json.loads(json_str)
                    except json.JSONDecodeError:
                        continue

                    if data.get("code") != 0:
                        logger.bind(tag=TAG).error( f"RAGFlow Chat 接口异常：{data.get('message', '未知错误')}")
                        break

                    resp_data = data.get("data")
                    if resp_data is True or (isinstance(resp_data, dict) and resp_data.get("final") is True):
                        break

                    answer_chunk = ""
                    if isinstance(resp_data, dict):
                        answer_chunk = resp_data.get("answer", "") or ""

                    if answer_chunk:
                        full_answer += answer_chunk
                        try:
                            from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType
                            conn.tts.tts_text_queue.put(
                                TTSMessageDTO(
                                    sentence_id=conn.sentence_id,
                                    sentence_type=SentenceType.MIDDLE,
                                    content_type=ContentType.TEXT,
                                    content_detail=answer_chunk,
                                )
                            )
                        except Exception:
                            pass
        else:
            import json
            response_text = resp.text
            result = json.loads(response_text)

            if result.get("code") != 0:
                error_msg = result.get("message", "未知错误")
                logger.bind(tag=TAG).error(f"RAGFlow Chat 非流式调用异常：{error_msg}")
                return ActionResponse(Action.RESPONSE, None, f"知识库查询异常：{error_msg}")

            data = result.get("data")
            if isinstance(data, dict):
                full_answer = data.get("answer", "") or ""
            elif isinstance(data, str):
                full_answer = data

        if full_answer:
            logger.bind(tag=TAG).info(
                f"RAGFlow Chat 回答完成，长度: {len(full_answer)} 字符"
            )
            return ActionResponse(Action.REQLLM, full_answer, None)

        logger.bind(tag=TAG).warning("RAGFlow Chat 返回空内容")
        return ActionResponse(Action.RESPONSE, None, "知识库查询未返回有效内容")

    except requests.exceptions.RequestException as e:
        error_type = type(e).__name__
        logger.bind(tag=TAG).error(
            f"RAGFlow Chat 网络请求失败，异常类型：{error_type}，详情：{str(e)}"
        )
        if isinstance(e, requests.exceptions.ConnectTimeout):
            error_response = "知识库连接超时"
        elif isinstance(e, requests.exceptions.ConnectionError):
            error_response = "无法连接到知识库服务"
        elif isinstance(e, requests.exceptions.Timeout):
            error_response = "知识库请求超时"
        elif isinstance(e, requests.exceptions.HTTPError):
            status_code = e.response.status_code if hasattr(e.response, "status_code") else "?"
            error_response = f"知识库HTTP错误（状态码：{status_code}）"
        else:
            error_response = f"知识库网络异常（{error_type}）"
        return ActionResponse(Action.RESPONSE, None, error_response)

    except Exception as e:
        error_type = type(e).__name__
        logger.bind(tag=TAG).error(
            f"RAGFlow Chat 处理异常，异常类型：{error_type}，详情：{str(e)}"
        )
        return ActionResponse(
            Action.RESPONSE, None, f"知识库处理异常：{str(e)[:50]}"
        )

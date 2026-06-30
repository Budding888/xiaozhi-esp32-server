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



'''
  配合意图识别，直接查询知识库
'''
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
    # ===== 检索参数优化：线上生产标准配置（腹膜透析患者问诊，推荐） =====
    # 1. 用 `vector_similarity_weight` 计算每一条知识库片段的**综合匹配分数**；
    # 2. 根据分数从高到低排序，取出前 `top_k` 条作为候选集合；
    # 3. 遍历候选集合，只保留综合分 ≥ `similarity_threshold` 的文档；
    # 4. 剩余文档送入重排/LLM。

    # top_k（粗召回条数）：向量库/索引库先根据综合得分，一次性取出分数最高的前 N 条作为候选池。只是控制最多取出几条。粗召回候选池12条，兼顾召回覆盖率与噪声控制
    top_k = min(ragflow_config.get("top_k", 12), 12)

    # similarity_threshold（综合分过滤阈值）：top_k 捞出一批候选后，用这条门槛过滤。只有 `综合得分 ≥ threshold` 的片段才保留，低分直接丢弃。综合分门槛0.6，过滤大部分弱相关片段
    similarity_threshold = max(ragflow_config.get("similarity_threshold", 0.6), 0.5)

    # vector_similarity_weight（打分权重系数）：提升语义权重，从根源减少“关键词碰瓷”的文档高分。
    # 向量语义为主，关键词为辅，适配患者口语提问
    #  整体作用：权重区间锁死在 [0.1, 0.9]：无论人为在配置里乱填多大 / 多小的数字，最终生效的 vector_similarity_weight 只会落在 0.1 ~ 0.9 之间：
    # 上限 0.9：防止向量权重 100%，完全丢弃 BM25 关键词检索，丢失字面精准匹配能力；
    # 下限 0.1：防止关键词权重 100%，完全丢弃语义向量，口语提问大量召回无关文档；
    # 默认值 0.7：医疗口语问答场景最优预设。
    vector_similarity_weight = max(0.1, min(0.9, float(ragflow_config.get("vector_similarity_weight", 0.7))))

    # 读取配置
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



'''
 调用知识库插件进行检索。配合医疗大模型使用
'''
@register_function(
    "search_from_ragflow_v2", SEARCH_FROM_RAGFLOW_FUNCTION_DESC, ToolType.SYSTEM_CTL
)
def search_from_ragflow_v2(conn: "ConnectionHandler", question=None):
    logger.bind(tag=TAG).info(f"===========触发知识库问答(search_from_ragflow_v2)===========，问题: {question}")
    # 确保字符串参数正确处理编码
    if question and isinstance(question, str):
        pass
    else:
        question = str(question) if question is not None else ""

    ragflow_config = conn.config.get("plugins", {}).get("search_from_ragflow", {})
    base_url = ragflow_config.get("base_url", "")
    api_key = ragflow_config.get("api_key", "")
    dataset_ids = ragflow_config.get("dataset_ids", [])

    # ===== 检索参数优化：线上生产标准配置（腹膜透析患者问诊，推荐） =====
    # 1. 用 `vector_similarity_weight` 计算每一条知识库片段的**综合匹配分数**；
    # 2. 根据分数从高到低排序，取出前 `top_k` 条作为候选集合；
    # 3. 遍历候选集合，只保留综合分 ≥ `similarity_threshold` 的文档；
    # 4. 剩余文档送入重排/LLM。

    # top_k（粗召回条数）：向量库/索引库先根据综合得分，一次性取出分数最高的前 N 条作为候选池。只是控制最多取出几条。粗召回候选池12条，兼顾召回覆盖率与噪声控制
    top_k = min(ragflow_config.get("top_k", 12), 12)

    # similarity_threshold（综合分过滤阈值）：top_k 捞出一批候选后，用这条门槛过滤。只有 `综合得分 ≥ threshold` 的片段才保留，低分直接丢弃。综合分门槛0.6，过滤大部分弱相关片段
    similarity_threshold = max(ragflow_config.get("similarity_threshold", 0.6), 0.5)

    # vector_similarity_weight（打分权重系数）：提升语义权重，从根源减少“关键词碰瓷”的文档高分。
    # 向量语义为主，关键词为辅，适配患者口语提问
    #  整体作用：权重区间锁死在 [0.1, 0.9]：无论人为在配置里乱填多大 / 多小的数字，最终生效的 vector_similarity_weight 只会落在 0.1 ~ 0.9 之间：
    # 上限 0.9：防止向量权重 100%，完全丢弃 BM25 关键词检索，丢失字面精准匹配能力；
    # 下限 0.1：防止关键词权重 100%，完全丢弃语义向量，口语提问大量召回无关文档；
    # 默认值 0.7：医疗口语问答场景最优预设。
    vector_similarity_weight = max(0.1, min(0.9, float(ragflow_config.get("vector_similarity_weight", 0.7))))

    # 读取配置
    req_timeout = ragflow_config.get("request_timeout", (10, 50))

    # 调用RagFlow知识库的检索接口
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
    logger.bind(tag=TAG).info(
        f"RAGFlow 检索参数: top_k={top_k}, threshold={similarity_threshold}, "
        f"vector_weight={vector_similarity_weight}"
    )

    try:
        # 使用带重试机制的 API 调用（网络异常和 5xx 自动重试 2 次）
        response = _call_ragflow_with_retry(url, headers, payload, req_timeout)
        # 显式设置响应的编码为utf-8
        response.encoding = "utf-8"
        # 先获取文本内容，然后手动处理JSON解码
        response_text = response.text

        import json
        result = json.loads(response_text)
        logger.bind(tag=TAG).debug(f"===========RAGFlow API调用成功，返回的原始结果===========：{result}")

        if result.get("code") != 0:
            error_detail = result.get("error", {}).get("detail", "未知错误")
            error_message = result.get("error", {}).get("message", "")
            error_code = result.get("code", "")
            logger.bind(tag=TAG).error(f"RAGFlow API调用失败，响应码：{error_code}，错误详情：{error_detail}")
            error_response = f"RAG接口返回异常（错误码：{error_code}）"
            if error_message:
                error_response += f"：{error_message}"
            if error_detail:
                error_response += f"\n详情：{error_detail}"
            return ActionResponse(Action.RESPONSE, None, error_response)

        chunks = result.get("data", {}).get("chunks", [])

        # ===== 多阶段过滤：相似度 → 内容质量 → 去重 → 截断 =====
        scored_chunks = []
        for chunk in chunks:
            content = chunk.get("content", "")
            if not content:
                continue
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
            elif not isinstance(content, str):
                content = str(content)

            content = content.strip()
            # 过滤过短chunk（纯噪音）
            if len(content) < 10:
                continue

            similarity = float(chunk.get("similarity", chunk.get("score", 1.0)))
            scored_chunks.append((similarity, content))

        # 按相似度降序排列
        scored_chunks.sort(key=lambda x: x[0], reverse=True)

        # 过滤低相关度chunk
        before_count = len(scored_chunks)
        scored_chunks = [(s, t) for s, t in scored_chunks if s >= similarity_threshold]
        after_count = len(scored_chunks)

        if before_count != after_count:
            logger.bind(tag=TAG).info(
                f"相似度阈值过滤: {before_count} -> {after_count} 个chunk (阈值={similarity_threshold})"
            )

        if after_count == 0 and before_count > 0:
            logger.bind(tag=TAG).warning(
                f"所有chunk均低于相似度阈值({similarity_threshold})，返回空结果"
            )

        # 内容去重：去除内容高度重叠的chunk（保留相似度更高的那个）
        deduped = []
        seen_texts = set()
        for score, content in scored_chunks:
            # 用前50字作为去重指纹（去掉空格和标点）
            fingerprint = content[:50].strip()
            if fingerprint not in seen_texts:
                seen_texts.add(fingerprint)
                deduped.append((score, content))

        if len(deduped) < len(scored_chunks):
            logger.bind(tag=TAG).info(
                f"内容去重: {len(scored_chunks)} -> {len(deduped)} 个chunk"
            )

        # 最终取 top 8（去重后控制输出量）
        final_chunks = deduped[:8]

        for score, content in final_chunks:
            logger.bind(tag=TAG).debug(f"chunk相似度={score:.4f}, 内容前40字: {content[:40]}...")

        if final_chunks:
            # 限制总内容长度，避免 MedicalQwen (2K上下文) token 超限
            MAX_TOTAL_LENGTH = 3000
            contents = []
            total_len = 0
            for _, content in final_chunks:
                if total_len + len(content) > MAX_TOTAL_LENGTH:
                    # 截断过长的最后一条
                    remain = MAX_TOTAL_LENGTH - total_len
                    if remain > 100:
                        contents.append(content[:remain] + "…")
                    break
                contents.append(content)
                total_len += len(content)

            context_text = f"# 关于问题【{question}】知识库的检索结果如下\n"
            context_text += "```\n\n\n".join(contents)
            context_text += "\n```"
            logger.bind(tag=TAG).info(
                f"RAGFlow 检索完成: {len(chunks)}个原始chunk → "
                f"{len(final_chunks)}个去重后chunk → "
                f"{total_len}字符内容"
            )
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



def ragflow_health_check(conn: "ConnectionHandler"):
    """
        RAGFlow 健康检查

        向 RAGFlow API 发送 GET 请求检测服务是否存活。
        超时 10 秒，避免阻塞主流程。

        Returns:
            bool: True=服务正常, False=不可用
        """
    # 读取配置
    ragflow_config = conn.config.get("plugins", {}).get("search_from_ragflow", {})
    base_url = ragflow_config.get("base_url", "")
    if not base_url:
        logger.bind(tag=TAG).error("RAGFlow Chat 配置不完整：缺少 base_url 或 api_key")
        return False

    url = base_url + "/api/v1/system/healthz"
    headers = { "Content-Type": "application/json",}

    try:
        # 调用RagFlow的健康检查接口
        response = requests.get(
            url=url,
            headers=headers,
            timeout=5,
            verify=False,
        )

        # 显式设置响应的编码为utf-8
        response.encoding = "utf-8"

        response.raise_for_status()

        # 先获取文本内容，然后手动处理JSON解码
        response_text = response.text
        import json
        result = json.loads(response_text)
        if response.status_code == 200 and result.get("status") == "ok":
            logger.bind(tag=TAG).info(f"===========RAGFlow服务健康检查【通过】===========")
            return True
        else:
            logger.bind(tag=TAG).error(f"===========RAGFlow服务健康检查【失败】===========")
            return False
    except Exception as e:
        error_type = type(e).__name__
        logger.bind(tag=TAG).error(f"RAGFlow服务健康检查异常，异常类型：{error_type}，详情：{str(e)}")
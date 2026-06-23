import requests
import json

from core.providers.llm import system_prompt

# 配置项
RAGFLOW_HOST = "http://127.0.0.1:8008"
CHAT_ID = "w18hS8UVepb-bGPV1j529RFcvs-3nYVQilkpO1x-bwI"
API_KEY = "ragflow-w18hS8UVepb-bGPV1j529RFcvs-3nYVQilkpO1x-bwI"
# 延长超时，适配长文本推理
REQUEST_TIMEOUT = 600

url = f"{RAGFLOW_HOST}/api/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

question = "血压特别高的原因"

system_prompt = "你依托专业医疗知识库为用户解答健康问题，作答必须优先使用检索到的资料。当知识库无相关内容时，再依据权威医学常识回复。全程保持医学术语准确、逻辑清晰，语言客观中立，不做诊断、不开处方，仅做健康知识科普。"


payload = {
    "question": "血压特别高的原因",
    "messages": [
        {
            "role": "system",
            "content": "你是医疗知识库专属问答助手，优先基于检索到的知识库内容详细作答。当所有知识库内容都与问题无关时，可使用自身专业医疗知识解答，术语严谨、逻辑清晰。"
        },
        {
            "role": "user",
            "content": "血压特别高的原因",
        }
    ],
    "stream": True
}


def stream_chat():
    full_content = ""
    print("开始接收流式回复：\n")

    try:
        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            stream=True,
            timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()

        # 逐行解析 SSE 流式数据
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            # 剔除 SSE 标准前缀 data:
            if raw_line.startswith("data:"):
                json_str = raw_line[5:].strip()
                if not json_str:
                    continue

                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError:
                    continue

                # 接口异常判断
                if data.get("code") != 0:
                    print(f"\n接口异常：{data.get('message', '未知错误')}")
                    break

                resp_data = data.get("data")
                # 最终结束标记：data 为 true
                if resp_data is True:
                    print("\n\n✅ 流式传输完成")
                    break

                # 拼接并实时输出回答片段
                answer_chunk = resp_data.get("answer", "")
                if answer_chunk:
                    print(answer_chunk, end="", flush=True)
                    full_content += answer_chunk

                # 兜底 final 字段判断
                if resp_data.get("final") is True:
                    print("\n\n✅ 流式传输完成")
                    break

        # 输出完整结果
        print("\n" + "=" * 80)
        print("【完整回答内容】")
        print(full_content)

    except requests.exceptions.ReadTimeout:
        print("\n❌ 错误：接口读取超时")
        print("建议：1. 检查RAGFlow服务状态 2. 适当增大 REQUEST_TIMEOUT 超时时间")
    except requests.exceptions.ConnectionError:
        print("\n❌ 错误：无法连接 127.0.0.1:8008")
        print("建议：检查 RAGFlow 是否启动、端口是否正确、防火墙/代理是否拦截")
    except requests.HTTPError as e:
        print(f"\n❌ HTTP 请求错误：{e}")
    except Exception as e:
        print(f"\n❌ 未知异常：{str(e)}")


if __name__ == "__main__":
    stream_chat()
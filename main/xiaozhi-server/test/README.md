# Test 页面通信数据格式说明

本文档基于 `test_page.html` 及其 JS 模块代码、服务器端 `core/` 处理逻辑，总结语音对话和文字对话的完整数据格式、调用流程和消息示例。

---

## 目录

1. [连接流程](#1-连接流程)
2. [语音对话完整示例](#2-语音对话完整示例)
3. [文字对话完整示例](#3-文字对话完整示例)
4. [打断机制](#4-打断机制)
5. [MCP 工具通信](#5-mcp-工具通信)
6. [数据格式总结表](#6-数据格式总结表)

---

## 1. 连接流程

### 1.1 OTA 请求 (HTTP POST)

在拨号前，先向 OTA 服务器发送 POST 请求获取 WebSocket 地址。

**URL:** `POST http://127.0.0.1:8002/xiaozhi/ota/`

**Request Headers:**
```http
POST /xiaozhi/ota/ HTTP/1.1
Content-Type: application/json
Device-Id: AB:CD:EF:12:34:56
Client-Id: web_test_client
```

**Request Body:**
```json
{
    "version": 0,
    "uuid": "",
    "application": {
        "name": "xiaozhi-web-test",
        "version": "1.0.0",
        "compile_time": "2025-04-16 10:00:00",
        "idf_version": "4.4.3",
        "elf_sha256": "1234567890abcdef1234567890abcdef1234567890abcdef"
    },
    "ota": { "label": "xiaozhi-web-test" },
    "board": {
        "type": "Web测试设备",
        "ssid": "xiaozhi-web-test",
        "rssi": 0,
        "channel": 0,
        "ip": "192.168.1.1",
        "mac": "AB:CD:EF:12:34:56"
    },
    "flash_size": 0,
    "minimum_free_heap_size": 0,
    "mac_address": "AB:CD:EF:12:34:56",
    "chip_model_name": "",
    "chip_info": { "model": 0, "cores": 0, "revision": 0, "features": 0 },
    "partition_table": [{ "label": "", "type": 0, "subtype": 0, "address": 0, "size": 0 }]
}
```

**Response (成功):**
```json
{
    "websocket": {
        "url": "ws://127.0.0.1:8000/ws",
        "token": "eyJhbGciOiJIUzI1NiJ9...",
        "version": "1.0.0"
    },
    "ota": {
        "version": 1,
        "url": "http://127.0.0.1:8002/xiaozhi/ota/firmware.bin"
    }
}
```

**Response (未绑定设备):**
```json
{
    "code": 404,
    "message": "Device not found"
}
```

### 1.2 WebSocket 连接

从 OTA 响应中提取 `websocket.url` 和 `websocket.token`，拼接带参数的 WebSocket URL：

```
ws://127.0.0.1:8000/ws?authorization=Bearer eyJhbGciOiJIUzI1NiJ9...&device-id=AB:CD:EF:12:34:56&client-id=web_test_client
```

### 1.3 Hello 握手

**Client → Server (发送 hello):**
```json
{
    "type": "hello",
    "device_id": "AB:CD:EF:12:34:56",
    "device_name": "Web测试设备",
    "device_mac": "AB:CD:EF:12:34:56",
    "token": "",
    "features": {
        "mcp": true
    }
}
```

**Server → Client (hello 响应):**
```json
{
    "type": "hello",
    "version": 1,
    "transport": "websocket",
    "audio_params": {
        "format": "opus",
        "sample_rate": 24000,
        "channels": 1,
        "frame_duration": 60
    },
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

> 注意：服务器下发的音频采样率默认是 **24000 Hz**（可配置），而客户端上传的音频采样率固定为 **16000 Hz**。

### 1.4 MCP 初始化 (握手后自动发送)

**Server → Client (MCP initialize):**
```json
{
    "type": "mcp",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "payload": {
        "jsonrpc": "2.0",
        "id": "init-001",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "xiaozhi-server",
                "version": "1.0.0"
            }
        }
    }
}
```

> 如果服务器支持视觉分析，`initialize` 的 `params.capabilities.vision` 中会包含视觉分析服务的 URL 和 Token。

**Client → Server (回复 initialize):**
```json
{
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "type": "mcp",
    "payload": {
        "jsonrpc": "2.0",
        "id": "init-001",
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "xiaozhi-web-test",
                "version": "2.1.0"
            }
        }
    }
}
```

---

## 2. 语音对话完整示例

### 2.1 完整交互序列

```
客户端 (浏览器)                                   服务器
    │                                               │
    │  1. 录音开始 → 采集麦克风 PCM (16kHz/单声道)    │
    │  2. Opus 编码 → 发送二进制 Opus 帧 ──────────→ │
    │  3. 持续发送 Opus 二进制音频帧 ──────────────→  │
    │  4. 停止录音 → 发送空帧 (长度0) ──────────────→ │
    │                               [ASR 语音识别]   │
    │  5. ←────────── {"type":"stt","text":"..."}   │
    │                               [Intent 意图]    │
    │                               [LLM 生成回复]    │
    │  6. ←────── {"type":"tts","state":"start"}    │
    │  7. ←────── {"type":"llm","text":"...","emotion":"..."}  │
    │  8. ←──{"type":"tts","state":"sentence_start","text":"..."}  │
    │  9. ←─── 二进制 Opus 音频帧 (TTS合成语音) ───── │
    │ 10. ←─── 二进制 Opus 音频帧 ────────────────── │
    │ 11. ←──{"type":"tts","state":"sentence_end","text":"..."}  │
    │ 12. ←──{"type":"tts","state":"sentence_start","text":"..."}  │
    │ 13. ←─── 二进制 Opus 音频帧 ────────────────── │
    │ 14. ←────────── {"type":"tts","state":"stop"}　│
    │                                               │
```

### 2.2 上行：客户端发送音频

#### 音频参数

| 参数 | 值 |
| --- | --- |
| 原始格式 | PCM Int16, 16kHz, 单声道 |
| 编码格式 | Opus (VoIP 模式) |
| 帧大小 | 960 samples/帧 (60ms @ 16kHz) |
| 编码参数 | bitrate=16kbps, complexity=5, DTX=1 |
| 传输方式 | WebSocket 二进制帧 (Uint8Array) |

#### 发送过程

**Step 1: 开始录音**
- 无需发送任何消息通知服务器，直接发送 Opus 编码后的二进制音频数据

**Step 2: 发送音频数据 (循环)**

每一帧原始 PCM 长度为 960 个 Int16 样本 (1920 字节)，编码为 Opus 后约 20~120 字节，通过 WebSocket 二进制帧发送：

```
WebSocket Binary Frame (Uint8Array):
[Opus encoded data: 0xXX 0xXX 0xXX ...]   (长度: ~20~120 字节)
```

JavaScript 代码示意：
```javascript
// PCM 数据编码为 Opus
const pcmData = new Int16Array(960);  // 60ms 音频
const opusData = opusEncoder.encode(pcmData);
websocket.send(opusData.buffer);       // 发送二进制帧
```

**Step 3: 停止录音**

发送一个长度为 0 的二进制帧表示录音结束：

```javascript
websocket.send(new Uint8Array(0));  // 空帧 = 录音结束标志
```

### 2.3 下行：服务器返回

#### Step 1: STT 识别结果

服务器完成 ASR 语音识别后，先返回识别到的文字：

```json
{
    "type": "stt",
    "text": "今天天气怎么样",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

#### Step 2: TTS 开始通知

```json
{
    "type": "tts",
    "state": "start",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

#### Step 3: LLM 文字回复

服务器返回 LLM 生成的完整回复文本（包含可选的 `emotion` 字段）：

```json
{
    "type": "llm",
    "text": "今天天气晴朗，气温25度，适合外出活动哦！😊",
    "emotion": "happy",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

#### Step 4 ~ N: TTS 分句语音和文本

服务器逐句合成语音，逐句下发（**文本消息**和**二进制音频帧**交替或并行）：

**句子 1 开始：**
```json
{
    "type": "tts",
    "state": "sentence_start",
    "text": "今天天气晴朗，气温25度，适合外出活动哦！😊",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**句子 1 二进制音频数据 (多个 Opus 帧)：**
```
WebSocket Binary Frame 1: [Opus frame 1: 0xXX ...]   (TTS 合成语音数据)
WebSocket Binary Frame 2: [Opus frame 2: 0xXX ...]
WebSocket Binary Frame N: [Opus frame N: 0xXX ...]
```

> 服务器音频参数：Opus 编码, 采样率 **24000 Hz**（与客户端上传的 16000 Hz 不同），单声道，每帧 60ms。

**句子 1 结束：**
```json
{
    "type": "tts",
    "state": "sentence_end",
    "text": "今天天气晴朗，气温25度，适合外出活动哦！😊",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

#### Step Final: TTS 播放结束

```json
{
    "type": "tts",
    "state": "stop",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

> 收到 `stop` 后，客户端必须清空所有音频缓冲并停止播放。

### 2.4 语音对话客户端处理流程

```
User presses record
    ↓
[Optional] If server is speaking → send abort message
    ↓
Start microphone capture (16kHz, mono)
    ↓
For each 960 PCM samples:
    → Opus encode → send binary frame via WebSocket
    ↓
User releases / stop recording
    ↓
Send empty binary frame (length 0)
    ↓
Wait for server responses...

Server responses arrive:
    ↓
{"type":"stt","text":"..."}       → Display as user message bubble
    ↓
{"type":"tts","state":"start"}    → Prepare audio player, start Live2D talking anim
    ↓
Binary Opus frames → Decode → Queue → Play via Web Audio API
    ↓
{"type":"tts","state":"sentence_start","text":"..."} → Display text in chat
    ↓
{"type":"tts","state":"sentence_end","text":"..."}   → (continue playing)
    ↓
{"type":"tts","state":"stop"}     → Clear buffers, stop Live2D anim
```

---

## 3. 文字对话完整示例

### 3.1 完整交互序列

```
客户端 (浏览器)                                   服务器
    │                                               │
    │  1. 用户在输入框输入文字，按 Enter             │
    │     先检查: 如果服务器正在说话?                │
    │     → 是: 先发送 abort 消息                   │
    │                                               │
    │  2. ──── {"type":"listen","state":"detect",    │
    │          "text":"你好，你是谁？"} ────────────→ │
    │                               [Intent 意图]    │
    │                               [LLM 生成回复]    │
    │  3. ←── {"type":"stt","text":"你好，你是谁？"} │
    │  4. ←── {"type":"tts","state":"start"}        │
    │  5. ←── {"type":"llm","text":"我是小智..."}   │
    │  6. ←── {"type":"tts","state":"sentence_start","text":"我是..."}  │
    │  7. ←── 二进制 Opus 音频帧 (TTS) ────────────  │
    │  8. ←── {"type":"tts","state":"sentence_end"} │
    │  9. ←── {"type":"tts","state":"stop"}         │
    │                                               │
```

### 3.2 上行：发送文字消息

#### 正常发送

**Client → Server:**
```json
{
    "type": "listen",
    "state": "detect",
    "text": "你好，你是谁？"
}
```

#### 唤醒词发送

如果 `text` 内容匹配配置中的 `wakeup_words`（如"你好小乐"），则发送：

```json
{
    "type": "listen",
    "state": "detect",
    "text": "你好小乐"
}
```

> 服务器对唤醒词会回复预设的欢迎语（如"我一直都在呢，您请说。"），不会触发 LLM 回答。

#### 打断后发送

如果发送文字时服务器正在播报语音（即上一轮对话尚未结束），客户端先发送 abort：

**Client → Server (打断消息):**
```json
{
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "type": "abort",
    "reason": "wake_word_detected"
}
```

紧接着发送文字消息：
```json
{
    "type": "listen",
    "state": "detect",
    "text": "等一下，我问另一个问题"
}
```

#### 语音控制模式

`listen` 消息也可用于控制语音检测模式（语音对话时由真实 ESP32 设备发送）：

```json
{
    "type": "listen",
    "state": "start",
    "mode": "manual"
}
```

```json
{
    "type": "listen",
    "state": "stop"
}
```

### 3.3 下行：服务器返回

#### Step 1: STT 消息（回显文字）

服务器将用户文字回显（类似语音识别的效果）：

```json
{
    "type": "stt",
    "text": "你好，你是谁？",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

#### Step 2: TTS 开始通知

```json
{
    "type": "tts",
    "state": "start",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

#### Step 3: LLM 文字回复

```json
{
    "type": "llm",
    "text": "你好呀！我是小智，你的智能语音助手，很高兴为你服务！有什么我可以帮你的吗？😊",
    "emotion": "happy",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

#### Step 4: TTS 分句语音

**句子 1 开始：**
```json
{
    "type": "tts",
    "state": "sentence_start",
    "text": "你好呀！我是小智，你的智能语音助手，很高兴为你服务！",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**音频数据 (二进制 Opus 帧)：**
```
[Opus binary frames...]
```

**句子 1 结束：**
```json
{
    "type": "tts",
    "state": "sentence_end",
    "text": "你好呀！我是小智，你的智能语音助手，很高兴为你服务！",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**句子 2 开始：**
```json
{
    "type": "tts",
    "state": "sentence_start",
    "text": "有什么我可以帮你的吗？😊",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**音频数据 (二进制 Opus 帧)：**
```
[Opus binary frames...]
```

**句子 2 结束：**
```json
{
    "type": "tts",
    "state": "sentence_end",
    "text": "有什么我可以帮你的吗？😊",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

#### Step Final: TTS 结束

```json
{
    "type": "tts",
    "state": "stop",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

### 3.4 附：触发 Function Call 的情况

如果用户的问题需要调用工具（如查询天气、播放音乐等），服务器的交互序列会有所不同，在 `llm` 回复之前会先调用工具：

```
Client → Server: {"type":"listen","state":"detect","text":"今天天气怎么样"}
    ↓
Server → Client: {"type":"stt","text":"今天天气怎么样","session_id":"..."}
Server → Client: {"type":"tts","state":"start","session_id":"..."}
    ↓
[Server 内部: LLM 识别到需要调用天气工具]
[Server 内部: 执行天气查询函数]
[Server 内部: 将工具返回结果再次送入 LLM 生成回答]
    ↓
Server → Client: {"type":"llm","text":"今天天气晴朗，气温25度...","emotion":"happy","session_id":"..."}
Server → Client: {"type":"tts","state":"sentence_start","text":"今天天气晴朗..."}
Server → Client: [Opus binary audio frames...]
Server → Client: {"type":"tts","state":"stop"}
```

> 工具调用的整个过程在服务器内部完成，客户端只看到最终的 LLM 回复和 TTS 语音。

---

## 4. 打断机制

### 4.1 打断消息格式

当用户发起新的交互时（录音或输入文字），如果服务器正在播报语音，客户端必须先发送打断消息：

**Client → Server:**
```json
{
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "type": "abort",
    "reason": "wake_word_detected"
}
```

### 4.2 打断后的服务器响应

**Server → Client:**
```json
{
    "type": "tts",
    "state": "stop",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

> 服务器收到 abort 后，会立即停止 LLM 生成和 TTS 合成，清空所有音频队列，并回复一个 `tts state=stop` 消息。

### 4.3 触发条件

| 场景 | 触发时机 | 动作 |
| --- | --- | --- |
| 录音 | 用户按下录音按钮时，如果 `isRemoteSpeaking == true` | 先发 abort，再开始录音发音频 |
| 文字输入 | 用户在输入框按 Enter，如果 `isRemoteSpeaking == true` | 先发 abort，再发送 listen 消息 |

---

## 5. MCP 工具通信

### 5.1 服务器下发 MCP 消息

```json
{
    "type": "mcp",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "payload": {
        "jsonrpc": "2.0",
        "id": "req-001",
        "method": "initialize",
        "params": {}
    }
}
```

### 5.2 客户端回复 MCP 消息

#### 回复 `initialize`

**Server → Client:**
```json
{
    "type": "mcp",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "payload": {
        "jsonrpc": "2.0",
        "id": "init-001",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "xiaozhi-server",
                "version": "1.0.0"
            }
        }
    }
}
```

**Client → Server:**
```json
{
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "type": "mcp",
    "payload": {
        "jsonrpc": "2.0",
        "id": "init-001",
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "xiaozhi-web-test",
                "version": "2.1.0"
            }
        }
    }
}
```

> 如果响应中包含 `capabilities.vision`，客户端可以提取视觉分析服务的 URL 和 Token 用于拍照分析。

#### 回复 `tools/list`

**Server → Client:**
```json
{
    "type": "mcp",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "payload": {
        "jsonrpc": "2.0",
        "id": "list-001",
        "method": "tools/list"
    }
}
```

**Client → Server:**
```json
{
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "type": "mcp",
    "payload": {
        "jsonrpc": "2.0",
        "id": "list-001",
        "result": {
            "tools": [
                {
                    "name": "get_device_status",
                    "description": "获取设备当前状态",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                },
                {
                    "name": "set_led_color",
                    "description": "设置设备LED灯颜色",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "color": {
                                "type": "string",
                                "description": "颜色值 (red/green/blue)"
                            },
                            "brightness": {
                                "type": "integer",
                                "description": "亮度 (0-100)",
                                "minimum": 0,
                                "maximum": 100
                            }
                        },
                        "required": ["color"]
                    }
                }
            ]
        }
    }
}
```

#### 回复 `tools/call` 成功

**Server → Client:**
```json
{
    "type": "mcp",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "payload": {
        "jsonrpc": "2.0",
        "id": "call-001",
        "method": "tools/call",
        "params": {
            "name": "set_led_color",
            "arguments": {
                "color": "red",
                "brightness": 80
            }
        }
    }
}
```

**Client → Server:**
```json
{
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "type": "mcp",
    "payload": {
        "jsonrpc": "2.0",
        "id": "call-001",
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": "{\"success\": true, \"message\": \"LED已设置为红色，亮度80%\"}"
                }
            ],
            "isError": false
        }
    }
}
```

#### 回复 `tools/call` 失败

```json
{
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "type": "mcp",
    "payload": {
        "jsonrpc": "2.0",
        "id": "call-001",
        "error": {
            "code": -32603,
            "message": "工具执行失败: 设备未响应"
        }
    }
}
```

### 5.3 视觉分析配置

当收到 MCP `initialize` 消息时，若 `payload.params.capabilities.vision` 存在，客户端从中提取视觉分析服务信息：

```json
{
    "payload": {
        "params": {
            "capabilities": {
                "vision": {
                    "url": "http://127.0.0.1:8003/mcp/vision/explain",
                    "token": "vision_service_token_xxx"
                }
            }
        }
    }
}
```

客户端保存该信息后，拍照时使用以下 HTTP 请求进行视觉分析：

```http
POST {vision.url}
Content-Type: multipart/form-data
Device-Id: AB:CD:EF:12:34:56
Client-Id: web_test_client
Authorization: Bearer {vision.token}

Form Data:
  question: "描述一下看到的物品"
  image: <JPEG 图片二进制数据>
```

---

## 6. 数据格式总结表

| 方向 | 消息类型 | 数据格式 | 详细说明 |
| --- | --- | --- | --- |
| **上行** | 语音数据 | 二进制 Opus 帧 | 16kHz/单声道, 960 samples/帧 (60ms), VoIP 模式编码 |
| **上行** | 录音结束 | 二进制空帧 | `new Uint8Array(0)` 长度 0 的二进制帧 |
| **上行** | 文字消息 | JSON | `{"type":"listen","state":"detect","text":"..."}` |
| **上行** | 语音控制 | JSON | `{"type":"listen","state":"start\|stop","mode":"manual"}` |
| **上行** | 打断 | JSON | `{"type":"abort","session_id":"...","reason":"wake_word_detected"}` |
| **上行** | Hello | JSON | `{"type":"hello","device_id":"...","device_mac":"...","features":{"mcp":true}}` |
| **上行** | MCP回复 | JSON | `{"type":"mcp","session_id":"...","payload":{"jsonrpc":"2.0","id":"...","result":{...}}}` |
| **下行** | 音频数据 | 二进制 Opus 帧 | 24kHz/单声道 (可配置), TTS 合成语音 |
| **下行** | Hello响应 | JSON | `{"type":"hello","session_id":"...","audio_params":{...}}` |
| **下行** | ASR识别 | JSON | `{"type":"stt","text":"...","session_id":"..."}` |
| **下行** | LLM回复 | JSON | `{"type":"llm","text":"...","emotion":"...","session_id":"..."}` |
| **下行** | TTS状态 | JSON | `{"type":"tts","state":"start\|sentence_start\|sentence_end\|stop","session_id":"...","text":"..."}` |
| **下行** | MCP调用 | JSON | `{"type":"mcp","session_id":"...","payload":{"jsonrpc":"2.0","method":"...","params":{...}}}` |
| **下行** | MCP初始化含视觉 | JSON | `{"type":"mcp","payload":{"method":"initialize","params":{"capabilities":{"vision":{"url":"...","token":"..."}}}}}` |

---

## 附录：关键音频参数

| 参数 | 上行 (客户端→服务器) | 下行 (服务器→客户端) |
| --- | --- | --- |
| **编码格式** | Opus | Opus |
| **采样率** | 16000 Hz (固定) | 24000 Hz (可配置) |
| **声道数** | 1 (单声道) | 1 (单声道) |
| **帧时长** | 60ms (960 samples) | 60ms |
| **位率** | 16 kbps | (TTS 引擎决定) |
| **应用模式** | VoIP (2048) | - |
| **复杂度** | 5 | - |
| **DTX** | 启用 | - |
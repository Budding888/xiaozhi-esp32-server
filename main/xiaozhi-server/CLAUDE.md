# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`xiaozhi-esp32-server` is a backend system for ESP32-based smart voice assistants. It provides real-time speech interaction (ASR → LLM → TTS), IoT device control, and a web management console.

Four components:
- **xiaozhi-server** (port 8000) — Python AI engine, WebSocket server for ESP32 devices
- **manager-api** (port 8002) — Java Spring Boot admin REST API
- **manager-web** (port 8001) — Vue.js 2 admin console (Element UI)
- **manager-mobile** — uni-app + Vue 3 cross-platform mobile app

## xiaozhi-server Architecture (this directory)

### Key Patterns

**Provider Pattern** (`core/providers/`): Each AI capability (ASR, TTS, LLM, VAD, Memory, Intent, VLLM) has an abstract base class in its subdirectory. Concrete implementations (e.g., `asr/fun_local.py`, `tts/edge_tts.py`, `llm/openai.py`) inherit from the base. Selection happens via `selected_module` in `config.yaml` and modules are initialized in `core/utils/modules_initialize.py`.

**Plugin System** (`plugins_func/`): Functions in `plugins_func/functions/` are auto-loaded by `loadplugins.py` and registered via the `@register_function(name, desc)` decorator from `register.py`. The decorator stores `FunctionItem` objects in `all_function_registry`. Each plugin maps to an LLM tool call — LLM sees the function name, description, and parameter schema, then decides when to invoke it.

**Message Handling** (`core/handle/`): Each WebSocket connection gets a `ConnectionHandler` (`core/connection.py`). Incoming messages are dispatched to handler modules:
- `helloHandle.py` — device handshake/authentication
- `receiveAudioHandle.py` — audio stream → VAD → ASR
- `textHandle.py` / `intentHandler.py` — text → LLM / intent recognition
- `functionHandler.py` — LLM function call execution
- `sendAudioHandle.py` — TTS → audio stream back to device
- `abortHandle.py` — interrupt handling
- `reportHandle.py` — device state reports

There's also a refactored `textHandler/` subdirectory with per-type message handlers (`helloMessageHandler.py`, `iotMessageHandler.py`, `mcpMessageHandler.py`, `abortMessageHandler.py`, etc.) — newer message processing lives here rather than the flat files.

### Tool Dispatch System (`core/providers/tools/`)

`UnifiedToolHandler` acts as the central router for LLM function calls. It categorizes tools into four types:
- **server_plugins/** — Python plugin functions from `plugins_func/functions/`
- **server_mcp/** — MCP client tools (third-party tool servers via WebSocket)
- **device_iot/** — IoT device control commands sent to ESP32 hardware
- **device_mcp/** — Device-side MCP client commands
- **mcp_endpoint/** — MCP endpoint connection management

This routing happens in `functionHandler.py` — when LLM returns a function call, `ConnectionHandler` passes it to `UnifiedToolHandler` which dispatches to the correct handler based on tool type.

### HTTP API Layer (`core/api/`)

Runs alongside the WebSocket server on port 8003. Provides:
- **`ota_handler.py`** — OTA firmware download endpoint for ESP32 devices
- **`vision_handler.py`** — `/mcp/vision/explain` endpoint for image analysis (forwarded to VLLM provider)

### MCP Integration

The server can connect to external MCP (Model Context Protocol) tool servers. Configured via `mcp_endpoint` in config.yaml (WebSocket URL). MCP tools are loaded and exposed to the LLM alongside built-in plugins. Supports both server-side and device-side MCP patterns.

### Performance Testing

`performance_tester.py` + `performance_tester/` directory provides load testing for WebSocket connections and LLM throughput.

### Config System

- `config.yaml` — main config (AI providers, plugins, prompts, server settings)
- `data/.config.yaml` — override file (takes precedence over `config.yaml`)
- `config_from_api.yaml` — remote config from `manager-api`
- Config loading: `config/settings.py` → `config/config_loader.py` (local merge) + `config/manage_api_client.py` (remote pull)
- `config/logger.py` — loguru-based logging with tag support (`logger.bind(tag=TAG)`)

### Key Directories

| Path | Purpose |
|------|---------|
| `core/connection.py` | Per-connection handler, orchestrates the full dialogue loop |
| `core/websocket_server.py` | WebSocket server, creates ConnectionHandler per device |
| `core/http_server.py` | HTTP server for OTA firmware downloads + vision API |
| `core/providers/` | AI service provider implementations (ASR, TTS, LLM, etc.) |
| `core/handle/` | Message processing pipeline modules |
| `core/handle/textHandler/` | Per-type message handlers (hello, iot, mcp, abort, etc.) |
| `core/providers/tools/` | Tool dispatch layer: `UnifiedToolHandler` routes to server plugins, MCP clients, or device IoT commands |
| `core/api/` | HTTP API endpoints: OTA firmware handler, vision analysis handler |
| `core/utils/` | Utilities: module init, dialogue, prompt manager, auth, audio codec, GC manager, etc. |
| `core/utils/` | Utilities: module init, dialogue, prompt manager, auth, audio, etc. |
| `plugins_func/functions/` | Plugin functions (weather, news, music, IoT, health data, etc.) |
| `config/` | Configuration loading, logging, API client |
| `models/` | Local model files (SenseVoiceSmall, SileroVAD, sherpa-onnx) |
| `test/` | WebSocket test page, edge-tts demos, funasr demos |

### Plugin Registration Flow

1. Each function file in `plugins_func/functions/` defines a function decorated with `@register_function(name, desc)`
2. `loadplugins.auto_import_modules("plugins_func.functions")` loads all modules at startup
3. `FunctionRegistry` filters which functions to activate based on `Intent.{mode}.functions` config list
4. LLM receives function descriptions as tool definitions and can invoke them via function calling

### Adding a New Plugin

Create a new file in `plugins_func/functions/` with:
```python
from plugins_func.register import register_function, Action, ActionResponse

@register_function("my_function_name", "Description that LLM will see")
def my_function(arg1: str, arg2: int) -> ActionResponse:
    # ... do something ...
    return ActionResponse(Action.REQLLM, result="result string")
```
Then add `my_function_name` to the `functions` list under the active intent mode in `config.yaml`.

### Adding a New AI Provider

1. Create a new file in the appropriate `core/providers/{type}/` directory
2. Implement the abstract base class (e.g., `ASRProviderBase` from `asr/base.py`)
3. Add the provider config entry under `{TYPE}:` in `config.yaml`
4. Set `selected_module.{TYPE}` to your provider name

## Commands

```bash
# Run xiaozhi-server
python app.py

# Install dependencies
pip install -r requirements.txt

# Test with web client
# Open test/test_page.html in browser (connects via WebSocket to localhost:8000)

# Docker (server only)
docker-compose up -d

# Docker (all components)
docker-compose -f docker-compose_all.yml up -d
```

## Python Dependencies

Python 3.10 recommended. Key pinned deps: torch 2.2.2, torchaudio 2.2.2, numpy 1.26.4, websockets 14.2. Full list in `requirements.txt`.

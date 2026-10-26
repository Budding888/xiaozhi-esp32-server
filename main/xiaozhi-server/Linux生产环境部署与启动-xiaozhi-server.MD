
# 1.项目虚拟环境的创建与管理
## 1.1 创建conda虚拟环境
```
conda create -n xiaozhi-esp32-server python=3.11
```
---

## 1.2 激活conda虚拟环境
```
conda activate xiaozhi-esp32-server
```
---

## 1.3 安装项目依赖
```
python -m pip install --upgrade pip
```
---

```
pip install -r requirements.txt
```
---


## 1.4 退出虚拟环境
```
conda deactivate
```
---

## 1.5 删除虚拟环境（若需重建）
```
conda remove -n xiaozhi-esp32-server --all
```


## 1.6 查看所有 Conda 环境
```
conda info --envs
```
---

---------------------------------------------------------------------------------------



# 2. 生产环境启动、停止服务
## 2.1 必须 先 激活虚拟环境
```
conda activate xiaozhi-esp32-server
```


## 2.2 在虚拟环境中 执行项目的启动脚本

```
sh deploy-xiaozhi-server.sh start

```

## 2.3 验证启动是否成功
### 启动 deploy_api_server_1.sh 时

> 浏览器访问：http://8.137.151.255:8106/health
> 
> 正常返回：{"status":"healthy","status_code":200,"backend":"llama-server","model":"Qwen3.5-Medical-GSPO.Q4_K_M.gguf","parallel_slots":4,"uptime_seconds":1792721845,"slots":{"status":"ok"}}



### 启动 deploy_api_server_2.sh 时

> 浏览器访问：http://8.137.151.255:8104/health
> 
> 正常返回：{"status":"healthy","status_code":200,"backend":"llama-server","model":"Qwen3.5-Medical-GSPO.Q4_K_M.gguf","parallel_slots":4,"uptime_seconds":1792721845,"slots":{"status":"ok"}}





# 3. app.py启动过程中的问题【下面出现的问题必须解决，否则app.py无法正常启动】

## 3.1 启动环境问题 1: 
>（1）python包缺失：**aioconsole**  
>（2）系统底层库缺失：**libopus**（opuslib_next 只是Python绑定，依赖系统的opus动态库）

```angular2html
Traceback (most recent call last):
  File "/usr/local/myproject/xiaozhi-server/app.py", line 37, in <module>
    from aioconsole import ainput
ModuleNotFoundError: No module named 'aioconsole'
Traceback (most recent call last):
  File "/usr/local/myproject/xiaozhi-server/app.py", line 37, in <module>
    from aioconsole import ainput
ModuleNotFoundError: No module named 'aioconsole'
    
Traceback (most recent call last):
  File "/usr/local/myproject/xiaozhi-server/app.py", line 40, in <module>
    from core.utils.util import get_local_ip, validate_mcp_endpoint
  File "/usr/local/myproject/xiaozhi-server/core/utils/util.py", line 11, in <module>
    import opuslib_next
  File "/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/site-packages/opuslib_next/__init__.py", line 19, in <module>
    from .exceptions import OpusError  # NOQA
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/site-packages/opuslib_next/exceptions.py", line 10, in <module>
    import opuslib_next.api.info
  File "/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/site-packages/opuslib_next/api/__init__.py", line 44, in <module>
    raise Exception("Could not find Opus library. Make sure it is installed.")
Exception: Could not find Opus library. Make sure it is installed.
    
Traceback (most recent call last):
  File "/usr/local/myproject/xiaozhi-server/app.py", line 40, in <module>
    from core.utils.util import get_local_ip, validate_mcp_endpoint
  File "/usr/local/myproject/xiaozhi-server/core/utils/util.py", line 11, in <module>
    import opuslib_next
  File "/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/site-packages/opuslib_next/__init__.py", line 19, in <module>
    from .exceptions import OpusError  # NOQA
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/site-packages/opuslib_next/exceptions.py", line 10, in <module>
    import opuslib_next.api.info
  File "/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/site-packages/opuslib_next/api/__init__.py", line 44, in <module>
    raise Exception("Could not find Opus library. Make sure it is installed.")
```

### 3.1.1 报错拆解
> 一共两个问题，顺序是：
> 1. `ModuleNotFoundError: No module named 'aioconsole'` → python包缺失：**aioconsole**
> 2. `Exception: Could not find Opus library. Make sure it is installed.` → 系统底层库缺失：**libopus**（opuslib_next 只是Python绑定，依赖系统的opus动态库）

> 环境：`anaconda3 / python3.11`，系统看起来是 Linux（Alibaba Cloud Linux / Ubuntu / Debian 都给你命令）

### 3.1.2 问题解决 
### （1）安装 aioconsole（Python包）
进入你的conda环境先：
```bash
conda activate xiaozhi-esp32-server
pip install aioconsole
```

### （2）安装系统 Opus 底层库（关键，解决后面这个Opus报错）
> ⚠️ 注意：这一步是**系统包管理器**，不是pip！opuslib_next 找的是系统so库

#### Ubuntu / Debian
```bash
apt update
apt install libopus-dev
```

#### Alibaba Cloud Linux 3 / CentOS / Rocky
```bash
yum install opus-devel
```

#### 如果是Alibaba Cloud Linux 4
```bash
dnf install opus-devel
```

#### 注意：安装完系统库之后，**重新进入conda环境，最好重装一次opuslib_next**，让它重新绑定：
```bash
conda activate xiaozhi-esp32-server
pip uninstall opuslib_next -y
pip install opuslib_next
```

### 3.1.3 验证是否修复
```bash
conda activate xiaozhi-esp32-server
python -c "import aioconsole; import opuslib_next; print('ok')"
```
输出ok就代表依赖全部就绪，可以启动 `app.py`

---

## 补充踩坑点（xiaozhi-esp32-server 常见）
1. 不要只用 `pip install opus`，没用；`opuslib_next` 依赖的是系统 `libopus.so`
2. 如果你是docker容器内运行，需要在Dockerfile里提前预装系统opus包
3. 有些精简容器（alpine）命令是 `apk add opus-dev`
4. 如果你装完依然报找不到opus：可以手动检查so文件
```bash
ldconfig -p | grep opus
```
看不到 libopus.so 就是系统库没装好





## 3.2 启动环境问题 2：找不到 ffmpeg 直接抛异常终止启动

### 3.2.1 报错信息
```angular2html
Exception: Could not find Opus library. Make sure it is installed.
/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/site-packages/pydub/utils.py:170: RuntimeWarning: Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work
  warn("Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work", RuntimeWarning)
从API读取配置
Traceback (most recent call last):
  File "/usr/local/myproject/xiaozhi-server/app.py", line 42, in <module>
    from core.websocket_server import WebSocketServer
  File "/usr/local/myproject/xiaozhi-server/core/websocket_server.py", line 33, in <module>
    from core.connection import ConnectionHandler
  File "/usr/local/myproject/xiaozhi-server/core/connection.py", line 33, in <module>
    from core.providers.tools.unified_tool_handler import UnifiedToolHandler
  File "/usr/local/myproject/xiaozhi-server/core/providers/tools/unified_tool_handler.py", line 12, in <module>
    from .server_mcp import ServerMCPExecutor
  File "/usr/local/myproject/xiaozhi-server/core/providers/tools/server_mcp/__init__.py", line 3, in <module>
    from .mcp_manager import ServerMCPManager
  File "/usr/local/myproject/xiaozhi-server/core/providers/tools/server_mcp/mcp_manager.py", line 12, in <module>
    from .mcp_client import ServerMCPClient
  File "/usr/local/myproject/xiaozhi-server/core/providers/tools/server_mcp/mcp_client.py", line 17, in <module>
    from mcp.client.streamable_http import streamablehttp_client
ImportError: cannot import name 'streamablehttp_client' from 'mcp.client.streamable_http' (/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/site-packages/mcp/client/streamable_http.py)
```



### 报错信息

```angular2html
ImportError: cannot import name 'streamablehttp_client' from 'mcp.client.streamable_http' (/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/site-packages/mcp/client/streamable_http.py)
/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/site-packages/pydub/utils.py:170: RuntimeWarning: Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work
  warn("Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work", RuntimeWarning)
从API读取配置
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.change_role' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.get_music_songs_list' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.get_news_from_chinanews' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.get_news_from_newsnow' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.get_time' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.get_weather' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.handle_exit_intent' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.hass_get_state' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.hass_init' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.hass_play_music' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.hass_set_state' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.play_music' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.search_from_ragflow' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.search_medical_question' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.submit_blood_glucose_data' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.submit_blood_pressure_data' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.submit_heart_rate_data' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.submit_urine_volume_data' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.submit_weight_data' 已加载
261024 15:56:58[0.9.2-00000000000000][plugins_func.loadplugins]-INFO-模块 'plugins_func.functions.update_medication_reminder_status' 已加载
Traceback (most recent call last):
  File "/usr/local/myproject/xiaozhi-server/core/utils/util.py", line 169, in check_ffmpeg_installed
    result = subprocess.run(
             ^^^^^^^^^^^^^^^
  File "/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/subprocess.py", line 548, in run
    with Popen(*popenargs, **kwargs) as process:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/subprocess.py", line 1026, in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
  File "/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/subprocess.py", line 1955, in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/usr/local/myproject/xiaozhi-server/app.py", line 266, in <module>
    asyncio.run(main())
  File "/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/asyncio/runners.py", line 190, in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
  File "/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/asyncio/runners.py", line 118, in run
    return self._loop.run_until_complete(task)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/root/anaconda3/envs/xiaozhi-esp32-server/lib/python3.11/asyncio/base_events.py", line 654, in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
  File "/usr/local/myproject/xiaozhi-server/app.py", line 160, in main
    check_ffmpeg_installed()
  File "/usr/local/myproject/xiaozhi-server/core/utils/util.py", line 217, in check_ffmpeg_installed
    raise ValueError("\n".join(error_msg)) from e
ValueError: ❌ 检测到 ffmpeg 无法正常运行。

建议您：
1. 确认已正确激活 conda 环境；
2. 查阅项目安装文档，了解如何在 conda 环境中安装 ffmpeg。

错误详情：
[Errno 2] No such file or directory: 'ffmpeg'

```

### 3.2.2 问题分析
> 现在情况变了：**项目代码里加了强校验函数 `check_ffmpeg_installed()`，不再只是警告，找不到 ffmpeg 直接抛异常终止启动**，必须装上 ffmpeg。
> 环境：Alibaba Cloud Linux 4。



### 3.2.3 方案A：系统全局静态ffmpeg（推荐，简单）【本次项目启动时 采用的是这个方法A】
```bash
# 下载静态版
wget [https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz](https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz)
# 如果wget超时换国内镜像
# wget [https://mirror.ghproxy.com/https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz](https://mirror.ghproxy.com/https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz)

tar -xf ffmpeg-release-amd64-static.tar.xz
cd ffmpeg-*-amd64-static
cp ffmpeg ffprobe /usr/local/bin/
chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe
cd ..
```
验证：
```bash
ffmpeg -version
which ffmpeg
```
> `/usr/local/bin` 默认在root的PATH里，装好之后再启动服务就能通过检测。




### 3.2.4  方案B：conda环境内安装ffmpeg（不用改系统，conda自带）
如果你不想往系统放二进制，直接在当前xiaozhi-esp32-server这个conda环境装ffmpeg：
```bash
conda activate xiaozhi-esp32-server
conda install -c conda-forge ffmpeg -y
```
✅ 优点：隔离在环境内部，不会污染系统；项目检测脚本可以识别到。
> 这个是alinux4下最省心的备选，避开系统源各种rpmfusion冲突。

## 同时确认MCP包版本（你之前的第一个报错还在吗？）
```bash
conda activate xiaozhi-esp32-server
pip list | grep mcp
```
必须是 `mcp 1.x`，不能是2.x；如果是2.x重新执行：
```bash
pip uninstall mcp -y
pip install "mcp>=1.0,<2.0"
```

## 确认opus（之前的opus报错）
```bash
python -c "import opuslib_next;print('opus ok')"
```
如果还报错：
```bash
dnf install opus-devel -y
pip uninstall opuslib_next -y
pip install opuslib_next
```



### 3.2.5  装好ffmpeg之后统一校验命令
```bash
conda activate xiaozhi-esp32-server
ffmpeg -version
python -c "
import aioconsole
import opuslib_next
from mcp.client.streamable_http import streamablehttp_client
print('✅ 全部依赖加载成功')
"
```



### 补充兜底：临时注释ffmpeg校验（仅调试，不建议长期）
如果只是先跑起来调试功能、暂时不需要音频转码，可以改文件：
`core/utils/util.py`，找到 `check_ffmpeg_installed()`，注释掉调用：
```python
# check_ffmpeg_installed()
```
> ⚠️ 只是临时绕过，后续音频转码功能会异常，正式使用还是要装ffmpeg。

优先试 **conda install -c conda-forge ffmpeg** 这条，alinux4 conda-forge源成功率很高。

---

### 执行顺序建议（直接复制）
```bash
conda activate xiaozhi-esp32-server
conda install -c conda-forge ffmpeg -y
ffmpeg -version
pip uninstall mcp -y
pip install "mcp>=1.0,<2.0"
dnf install opus-devel -y
pip uninstall opuslib_next -y
pip install opuslib_next
python -c "import opuslib_next; from mcp.client.streamable_http import streamablehttp_client; print('ok')"
```
全部ok之后再启动 `python app.py`





### 方案A 实施过程记录
(xiaozhi-esp32-server) [root@iZ2vcftc4aunr4n9ucf937Z xiaozhi-server]# conda deactivate
(base) [root@iZ2vcftc4aunr4n9ucf937Z xiaozhi-server]# cd /usr/local/javasoft
(base) [root@iZ2vcftc4aunr4n9ucf937Z javasoft]# wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
--2026-10-24 16:00:33--  https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
Resolving johnvansickle.com (johnvansickle.com)... 107.180.57.212
Connecting to johnvansickle.com (johnvansickle.com)|107.180.57.212|:443... connected.
HTTP request sent, awaiting response... 200 OK
Length: 41888096 (40M) [application/x-xz]
Saving to: ‘ffmpeg-release-amd64-static.tar.xz’

ffmpeg-release-amd64-static.tar.xz                       100%[===============================================================================================================================>]  39.95M   900KB/s    in 48s     

2026-10-24 16:01:21 (858 KB/s) - ‘ffmpeg-release-amd64-static.tar.xz’ saved [41888096/41888096]

(base) [root@iZ2vcftc4aunr4n9ucf937Z javasoft]# tar -xf ffmpeg-release-amd64-static.tar.xz
(base) [root@iZ2vcftc4aunr4n9ucf937Z javasoft]# ls
ffmpeg-7.0.2-amd64-static  ffmpeg-release-amd64-static.tar.xz  jdk  llama  nginx  redis  softupload
(base) [root@iZ2vcftc4aunr4n9ucf937Z javasoft]# cd ffmpeg-*-amd64-static
(base) [root@iZ2vcftc4aunr4n9ucf937Z ffmpeg-7.0.2-amd64-static]# ls
ffmpeg  ffprobe  GPLv3.txt  manpages  model  qt-faststart  readme.txt
(base) [root@iZ2vcftc4aunr4n9ucf937Z ffmpeg-7.0.2-amd64-static]# cp ffmpeg ffprobe /usr/local/bin/
(base) [root@iZ2vcftc4aunr4n9ucf937Z ffmpeg-7.0.2-amd64-static]# chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe
(base) [root@iZ2vcftc4aunr4n9ucf937Z ffmpeg-7.0.2-amd64-static]# d ..
-bash: d: command not found
(base) [root@iZ2vcftc4aunr4n9ucf937Z ffmpeg-7.0.2-amd64-static]# cd ..
(base) [root@iZ2vcftc4aunr4n9ucf937Z javasoft]# ffmpeg -version
ffmpeg version 7.0.2-static https://johnvansickle.com/ffmpeg/  Copyright (c) 2000-2024 the FFmpeg developers
built with gcc 8 (Debian 8.3.0-6)
configuration: --enable-gpl --enable-version3 --enable-static --disable-debug --disable-ffplay --disable-indev=sndio --disable-outdev=sndio --cc=gcc --enable-fontconfig --enable-frei0r --enable-gnutls --enable-gmp --enable-libgme --enable-gray --enable-libaom --enable-libfribidi --enable-libass --enable-libvmaf --enable-libfreetype --enable-libmp3lame --enable-libopencore-amrnb --enable-libopencore-amrwb --enable-libopenjpeg --enable-librubberband --enable-libsoxr --enable-libspeex --enable-libsrt --enable-libvorbis --enable-libopus --enable-libtheora --enable-libvidstab --enable-libvo-amrwbenc --enable-libvpx --enable-libwebp --enable-libx264 --enable-libx265 --enable-libxml2 --enable-libdav1d --enable-libxvid --enable-libzvbi --enable-libzimg
libavutil      59.  8.100 / 59.  8.100
libavcodec     61.  3.100 / 61.  3.100
libavformat    61.  1.100 / 61.  1.100
libavdevice    61.  1.100 / 61.  1.100
libavfilter    10.  1.100 / 10.  1.100
libswscale      8.  1.100 /  8.  1.100
libswresample   5.  1.100 /  5.  1.100
libpostproc    58.  1.100 / 58.  1.100
(base) [root@iZ2vcftc4aunr4n9ucf937Z javasoft]#




















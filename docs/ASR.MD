
## FunASRServer基础与安装

[FunASRServer（0.1.12 2pass 离线版）支持的方言清单](https://www.doubao.com/thread/wdc57148406a62137)
```
一、强支持（识别极准、原生优化、陕西话首选）
西北官话（你西安本地）
陕西关中话（西安方言）
甘肃兰州话、山西太原话、宁夏方言
西南官话
四川话、重庆话、云南话、贵州话
东北官话
东北三省方言、赤峰口音
华北官话
河南话、山东话、天津话、北京口音

二、良好支持
上海话、江浙吴语
湖南话、湖北话
粤语（两广白话，够用不如 SenseVoice 极致）
三、通用口音普通话
全国各类带口音普通话全部兼容
四、不支持小众方言
闽南语、潮汕话、客家话、温州话、少数民族语言
一句话适配你的场景
✅ 陕西西安本地话 → FunASRServer 全网本地 ASR 最强
✅ 四川 / 东北 / 河南 / 山东 → 碾压所有本地 ONNX 模型
❌ 极致粤语 → 换 Sherpa SenseVoice
```

[FunASRServer在docker中启动时关闭SSL](https://www.doubao.com/thread/w1acc805fe801e68c)

[error Handshake ended with HTTP error: 426 + 10095d端口占用等启动问题](https://www.doubao.com/thread/w450e20f3ce1b2fd0)
```
HTTP 426 = Upgrade Required / 需要升级协议
原因：你的客户端用 HTTP 连接，但服务端还在使用 WebSocket 标准

启动时强制使用纯 WebSocket 无验证模式

第一步：杀死旧进程（必须执行）
pkill -f funasr
pkill -f run_server_2pass
pkill -f "funasr-wss-server"


第二步：创建空热词文件（解决报错）
touch /workspace/models/hotwords.txt


nohup bash run_server_2pass.sh \
--download-model-dir /workspace/models \
--vad-dir damo/speech_fsmn_vad_zh-cn-16k-common-onnx \
--model-dir iic/SenseVoiceSmall-onnx \
--online-model-dir damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online-onnx \
--punc-dir damo/punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727-onnx \
--lm-dir damo/speech_ngram_lm_zh-cn-ai-wesp-fst \
--itn-dir thuduj12/fst_itn_zh \
--hotword /workspace/models/hotwords.txt \
--certfile "" \
--keyfile "" \
> log.txt 2>&1 &
```



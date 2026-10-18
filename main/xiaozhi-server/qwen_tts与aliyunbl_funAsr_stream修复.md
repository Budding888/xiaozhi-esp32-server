修复完成。以下是完整结论。

  根因：重构只做了一半

  core/providers/tts/qwen_audio_tts_single_stream.py 的 tts_text_priority_thread 调用了三个仓库里根本不存在的方法：

  ┌─────────────────┬────────────────────────┬────────────────────────────────────────────┐
  │    调用位置     │          方法          │                    后果                    │
  ├─────────────────┼────────────────────────┼────────────────────────────────────────────┤
  │ FIRST 分支 :381 │ reset_caption_stream() │ "启动TTS会话失败"，首条消息被丢弃          │
  ├─────────────────┼────────────────────────┼────────────────────────────────────────────┤
  │ TEXT 分支 :394  │ push_caption_text()    │ 异常发生在 text_to_speak() 之前            │
  ├─────────────────┼────────────────────────┼────────────────────────────────────────────┤
  │ LAST 分支 :423  │ flush_caption_text()   │ "结束TTS会话失败"，finish_session() 不执行 │
  └─────────────────┴────────────────────────┴────────────────────────────────────────────┘

  因为都被 try/except 吞掉并 continue，结果是 TEXT 分支既不提交文本给 TTS SDK（没有语音），也不下发 sentence_start（没有文字），LAST 也不执行（客户端收不到 stop）。测试复现出的原始报错：

  启动TTS会话失败: 'TTSProvider' object has no attribute 'reset_caption_stream'
  发送TTS文本失败: 'TTSProvider' object has no attribute 'push_caption_text'
  结束TTS会话失败: 'TTSProvider' object has no attribute 'flush_caption_text'

  时间戳证据：logs/server.log 最后一次成功运行是 19:19（当时无这些调用、无报错），而 qwen_audio_tts_single_stream.py(19:30)、xunfei_stream.py(19:31)、base.py(19:33)
  都是在那之后才被改动的——正是这次未完成的重构引入了故障。

  次生问题：双流式 TTS 直接调 SDK 合成、音频帧由回调推送，不经过基类 to_tts_stream()，所以从来没人下发过带文字的 sentence_start；19:17 日志里的 发送第一段语音: None 就是"有声音没文字"的表现。

  修复（仅 2 个文件）

  core/providers/tts/base.py 中实现三个共享钩子（放基类可同时修好 qwen 与讯飞，且不重复代码）：

  - reset_caption_stream() / push_caption_text() / flush_caption_text() — 累积 LLM 流式文本，凑齐一句立即下发；LAST 时补发尾部残句。
  - 切句策略复用基类既有标点集合（首句含逗号，更快出字）。
  - 下发复用既有 tts_audio_queue 的 FIRST 通道 → _audio_play_priority_thread → sendAudioMessage → sentence_start，天然继承 sentence_id 过滤、打断检查，以及与音频包的先后顺序。

  代码审查发现并已处理

  独立 python-reviewer 复审（结论：无 CRITICAL/HIGH），我逐条核实后处理了 2 个 MEDIUM：

  1. 字幕未清洗 markdown — 语音会 clean_markdown，字幕原来只会 .strip()，客户端会看到 **加粗**。已让 _emit_caption_sentence 走同一套清洗（check_emoji 幂等，重复调用安全）。
  2. report_on_last 提供方文本被覆盖 — _audio_play_priority_thread 的累积分支原来是 enqueue_text = text，多句字幕 FIRST 会把上报文本覆盖成只剩最后一句（影响讯飞/seed-tts-2.0 的聊天记录）。改为累加 (enqueue_text or "") +
     text。我核对了 alibl/aliyun/huoshan 三个同样 report_on_last=True 的提供方——它们只推一条带文本的 FIRST，累加与覆盖结果完全一致，属无风险改动。

  另外采纳了 LOW：sentence_id 未显式传入时回退为当前会话 sentence_id，避免将来调用方漏传时绕过陈旧轮次过滤。

  验证

  - 新增 tests/test_tts_caption_stream.py：先写红（14 failed，即上述 AttributeError）后转绿，现 20 passed。含端到端用例——断言客户端 websocket 真的收到 {"type":"tts","state":"sentence_start","text":...}；以及 markdown
    清洗、sentence_id 过滤、打断丢弃、report_on_last 全文上报等。
  - 全量：196 passed, 3 skipped；4 个失败项经 git stash core/providers/tts/base.py 对照确认是既有失败（3 个是其它流式 TTS 尚未完成同类重构、1 个 ASR 用例），与本次改动无关。

  你需要做的

  重启 xiaozhi-server 即可。另外提醒一点：你这套环境的 data/.config.yaml 配了 manager-api，实际生效的 TTS 配置来自智控台（config.yaml 里的 selected_module.TTS: EdgeTTS 并不生效，启动日志里实际加载的是
  TTS_AliBLQwenAudioStreamTTS）——所以调整音色/模型请改智控台，改 config.yaml 不会起作用。
  

--------------------------------------------------------

根因已定位并修复。以下是完整分析。
     
  这个报错不是网络问题
     
  request timeout after 23 seconds 里的 23 秒来自 SDK 自己：dashscope/audio/asr/recognition.py:137 有 SILENCE_TIMEOUT_S = 23,在 start() 时启动一个定时器，只要 23 秒没收到音频帧就把会话掐掉（_silence_stop_timer 里
  _running = False、join 工作线程、关闭 ws）。随后 send_audio_frame 抛 InvalidParameter('Speech recognition has stopped.')。
     
  日志统计印证了这一点（logs/server.log）：
     
  ┌─────────────────────────────────────────────────────────────────────┬──────┐
  │                                报错                                 │ 次数 │
  ├─────────────────────────────────────────────────────────────────────┼──────┤
  │ status=44, code=CLIENT_ERROR, msg=request timeout after 23 seconds. │ 75   │
  ├─────────────────────────────────────────────────────────────────────┼──────┤
  │ status=44, code=IdleTimeout, msg=Idle timeout!                      │ 31   │
  ├─────────────────────────────────────────────────────────────────────┼──────┤
  │ 发送音频帧失败: Speech recognition has stopped.                     │ 28   │
  └─────────────────────────────────────────────────────────────────────┴──────┘

  根因：会话开起来后没人关，服务端也就断不了句

  aliyunbl_funAsr_stream.py 的 receive_audio 在本地 VAD 检测到第一帧语音时建立识别会话，但：

  1. 一旦 audio_have_voice 变 False，代码就 return，不再发送任何音频帧；
  2. DashScope 服务端是靠音频流里的尾部静音来判断一句话结束的（max_sentence_silence）。不发音频帧，它既看不到语音结束、也不会返回 final；
  3. 而应用里"用户说完了"的标准信号 conn.client_voice_stop（静音 700ms 后由 SileroVAD 置位，silero.py:109-112）在自动模式下被完全忽略——原代码只在 manual 模式下消费它：

  if getattr(conn, "client_voice_stop", False) and self.is_processing:
      if getattr(conn, "client_listen_mode", "auto") == "manual":   # ← 自动模式直接漏掉

  于是会话就这么空转 23 秒被 SDK 掐死。这也解释了为什么只有少量 最终识别 成功——那些是用户连续说话、服务端能在流内找到停顿的长转录。

  修复（只改 core/providers/asr/aliyunbl_funAsr_stream.py）

  把 client_voice_stop 的处理从手动模式提升为两种模式通用，并放在无语音早退之前：

  if self.is_processing and getattr(conn, "client_voice_stop", False):
      conn.client_voice_stop = False          # 消费后清除
      self._mark_stop()
      asyncio.create_task(self._finalize_and_report())   # 内部 _cleanup 会 stop() 掉会话

  外加两处防误杀：_start_recognition 里清掉上一轮残留的 client_voice_stop，避免新会话刚建立就被立刻收尾。

  为什么这是安全的兜底而非行为改变：服务端若能自行断句（on_event 的 final，约 200ms），会先触发 _finalize_and_report 把 is_processing 置 False，我这个检查随后就是空操作；只有在服务端断不了句时，才由本地 VAD 的 700ms
  静音兜底收尾——从"卡 23 秒后报错"变成"约 0.7 秒内正常收尾并进入 LLM"。

  验证

  新增 tests/test_fun_asr_session_lifecycle.py：先写红（撤销修复后 5 failed）再转绿（7 passed）。覆盖：自动模式收尾、标记被消费、_stopped_flag 置位、手动模式行为保留、非处理中/未说完不收尾、新会话不继承残留标记。

  全量：203 passed, 3 skipped，4 个失败项与之前完全相同的既有失败。其中顺带查明了一个：test_asr_error_cleanup.py::test_on_error_does_not_raise_without_loop 是测试自身的 fixture 漏了一行（第 112 行的用例没像第 66
  行那样设置 provider._bridge = bridge，导致 _is_active() 直接返回、断言落空）——不是产品代码缺陷。要我一并补上这行吗？

  重启 xiaozhi-server 生效。



------------------------------------------------


修复完成并已用真实服务验证。
     
  文字太快的根因（已实测量化）
     
  我用你的 key 实测了一次完整合成，得到决定性数据：
     
  sentence-begin '晚上好呀，'                        audio_so_far=    0ms
  sentence-end   '晚上好呀，'                        audio_so_far= 1090ms
  sentence-begin '今天累不累？我给你讲个温柔的小故事吧。'  audio_so_far= 1090ms
  sentence-end   '今天累不累？…'                     audio_so_far= 4020ms
  ...
  COMPLETE                                       audio=47430ms

  228 个字、47.4 秒语音，服务端在 6.45 秒内就全部合成完了（约 8 倍速）。 而我上一版的字幕是按 LLM 出字的节奏下发的——文字在 ~6 秒内全部冒出来，音频却还要播 47
  秒，所以"文字远远跑在语音前面"。这不是显示问题，是字幕的节奏锚点选错了：锚在"文本产生"，而不是"语音播放"。

  修复：字幕改由服务端「句首事件」驱动

  实测发现服务端每个句子都会发事件，并带上该句原文：

  type='sentence-begin'  original_text='你好，今天天气怎么样？'   ← 该句音频紧随其后
  type='sentence-end'    original_text='你好，今天天气怎么样？'

  而且句首事件与它自己的音频帧由同一个 SDK 线程、同一条 WebSocket 按序到达（实测每个 sentence-begin 的 audio_so_far 恰好等于上一句的 sentence-end，即它精确落在音频边界上）。

  所以正确做法是：在句首事件到达时，把这句话的文字推入 tts_audio_queue。它与音频帧共用同一条队列，于是被排在自己这句话的音频之前，再交给既有的 _audio_play_priority_thread + AudioRateController——按
  60ms/帧的真实播放节奏发出。文字与语音天然同步，不再依赖 LLM 与 TTS 谁快谁慢。

  改动只在 core/providers/tts/qwen_audio_tts_single_stream.py：
  - _QwenAudioCallback 增加 on_sentence 钩子，识别 sentence-begin 并取出 original_text；
  - 新增 TTSProvider._on_sentence_begin()，复用基类的 _emit_caption_sentence()（含 markdown 清洗、打断检查、sentence_id 过滤）；
  - 移除 tts_text_priority_thread 里 reset_caption_stream / push_caption_text / flush_caption_text
    三个客户端侧调用——否则会重复下发，而且客户端断句与服务端实际断句不一致（实测服务端会把「嗯……你有没有觉得，有时候慢慢扎根，」单独成句，与客户端按逗号的切法不同）。现在显示的就是实际朗读的原文。

  xunfei_stream.py 不受影响（它没有这类事件，继续用基类的 push_caption_text）。

  验证

  tests/test_tts_caption_stream.py 扩到 28 passed，新增覆盖：句首事件下发字幕、sentence-end/synthesis 事件不重复下发、空文本与坏 JSON 容错、打断后不下发、start_session
  的接线，以及最关键的同步性回归用例——断言字幕确实被排在它自己那句话的音频帧之前。

  全量 211 passed, 3 skipped，仍是那 4 个既有失败（与本次无关）。重启 xiaozhi-server 生效。

  语速有点快

  这是 TTS 参数，不在代码里，在智控台（你这套环境的配置来自 manager-api，改 config.yaml 不生效）。当前生效值是 speech_rate: 1.0（ttsRate: 0）。

  在智控台的 TTS 配置里把 语速 ttsRate 调成 -20 即约 0.9 倍速（-40 约为 0.8 倍速）：

  ┌───────────┬──────────────────┐
  │  ttsRate  │ 实际 speech_rate │
  ├───────────┼──────────────────┤
  │ 0（当前） │ 1.0              │
  ├───────────┼──────────────────┤
  │ -20       │ 0.9              │
  ├───────────┼──────────────────┤
  │ -40       │ 0.8              │
  └───────────┴──────────────────┘

  映射来自基类 convert_percentage_to_range(p, 0.5, 2.0, 1.0)：1.0 + 0.5 × p/100。

  顺带一提：控制台中还有个 pitch_rate: 1.0（实测配置里 ttsPitch: 21），如果觉得音调也偏高可以一起调。

  如果你希望不依赖智控台、直接在代码里固定一个默认语速，告诉我，我可以改——但我更建议在智控台调，那样随时可调不用重启。
------------------------------------------------

双工联用报错修复（11:40:34 → 11:40:58 的 task-failed "request timeout after 23 seconds"）

  现象
    日志按序出现：
      11:40:34  发送音频消息: SentenceType.LAST, None
      11:40:34  TTS合成器不存在，正在重建会话后继续发送文本
      11:40:49  发送音频消息: SentenceType.FIRST, 检测到上一轮问题解答未完成...
      11:40:58  语音合成出现异常 ... request timeout after 23 seconds

  根因
    中断恢复机制会在「本轮 LLM 回答完成（LAST）」之后立刻追加一条
    MIDDLE 文本（询问用户是否继续被中断的问题）。这条 MIDDLE 到达时
    synthesizer 已被 LAST 的 finish_session 置空，于是 text_to_speak
    走「重建会话」分支，重新 start_session 出一个新合成器。

    随后 15 秒后，设备侧对恢复询问的确认/新一轮 chat 触发一个全新的
    FIRST（新的 sentence_id），其 start_session 会先关闭上一个会话。
    关键缺陷在 _close_synthesizer：它只做裸 ws.close()，没有先向服务端
    下发 finish-task（async_streaming_complete / streaming_cancel）。
    服务端会话不会被通知结束，于是残留 23 秒后被 SDK 以
    task-failed("request timeout after 23 seconds") 形式报错。

    这 23 秒来自服务端/SDK 的空闲看门狗，与 ASR 侧那次 23 秒超时同源
    但相互独立——本次只修 TTS 侧的「残留任务不收尾」。

  修复（仅 core/providers/tts/qwen_audio_tts_stream.py）
    - _close_synthesizer 增加 finish 参数（默认 True）：关闭前先通过
      run_in_executor 调用 SDK 的 async_streaming_complete() 下发结束请求，
      再 syn.close()。async_streaming_complete 只发请求立即返回、收尾由
      SDK 内部线程负责；任务未开始/已停止时由 _safe_sdk_call 吞掉预期的
      InvalidTask 异常。
    - start_session 内部「关闭上一个未结束 synthesizer」的调用因此自动获得
      优雅收尾（start_session → _close_synthesizer() 默认 finish=True），
      LAST 之后由 MIDDLE 触发的重建会话在下一轮 FIRST 到来时不再残留任务。

  验证
    - 新增 tests/test_asr_tts_interplay.py：先写红（裸 close 导致
      [('close',)]）后转绿（关闭前必须下发 finish 且 finish 在 close 之前），
      覆盖 _close_synthesizer、LAST 后 MIDDLE 重建、新一轮 FIRST 优雅关闭旧会话。
    - 顺带将 test_tts_caption_stream.py / test_tts_reconnect.py 里对旧模块名
      qwen_audio_tts_single_stream 的 import 改为 qwen_audio_tts_stream（之前
      因 rename 已无法收集；仅改 import 路径，未改断言逻辑）。
    - 全量（剔除 3 个已知既有失败 + 1 个 ASR 测试自身 fixture 缺陷）：
      184 passed, 3 skipped，无本次改动引入的失败。

------------------------------------------------

孤儿 TTS 会话修复（恢复询问重建出的会话从不收尾，23s 后被看门狗掐掉）

  现象
    上一节修完 _close_synthesizer 后，双工联用仍反复出现同一句报错
    （logs/server.log 里 11:40:34 → 11:40:58 是一次最干净的复现）：

      11:40:34  发送音频消息: SentenceType.FIRST, 比如体重、血压...
      11:40:34  发送音频消息: SentenceType.FIRST, 你再说一遍...
      11:40:34  发送音频消息: SentenceType.LAST, None        ← finish_session 关闭合成器，置 None
      11:40:34  WARNING: TTS合成器不存在，正在重建会话后继续发送文本
      11:40:49  发送音频消息: SentenceType.FIRST, 检测到上一轮问题解答未完成...
      11:40:58  语音合成出现异常: task-failed request timeout after 23 seconds

  根因（孤儿 TTS 会话）
    connection.py 的「中断恢复」逻辑在 LAST（本轮回答结束）之后紧接着又入队
    一条 MIDDLE（恢复询问文本）。TTS 线程按 FIFO 处理：

      1) LAST → finish_session() → _close_synthesizer() 关闭 synthesizer，
         并置 self.synthesizer = None；
      2) MIDDLE（恢复询问）→ text_to_speak() 发现 synthesizer 为 None →
         走「重建会话」分支，start_session() 新建合成器并 streaming_call() 提交文本。

    关键缺陷：这条重建出的会话后面没有任何 LAST 来收尾。它创建后一直空转，
    服务端（DashScope）的空闲看门狗 23 秒后判为
    task-failed "request timeout after 23 seconds"。同时因为它从不 FINISH，
    SDK 的 on_complete 永不触发，客户端播放也拿不到收尾标记。

    上一节的 _close_synthesizer 修复只解决了「下一个 FIRST 到来时优雅关闭旧
    会话」，没有解决「恢复 MIDDLE 重建出的孤儿会话本身从不被收尾」——这正是
    本节要补的。日志里的 15 秒间隔（streaming_call 首次建连阻塞）与 23 秒超时点
    全部对得上，是与用户报告唯一完全吻合的根因。

  修复（仅 core/connection.py）
    把三处重复的「恢复询问入队」收敛为一个方法
    ConnectionHandler._enqueue_resume_query_tts()：先发 MIDDLE 文本，紧跟
    一条 LAST，让重建会话通过 finish_session 下发 FINISH 自我收尾。

      LAST(主回答) ──▶ MIDDLE(恢复询问) ──▶ LAST(新增, 收尾恢复会话)

    三个调用点（均为「检测到上一轮问题解答未完成...」的恢复分支）：
      - connection.py:1364  chat()（常规 LLM，日志里的主路径）
      - connection.py:1444  _agentscope_chat()（AgentScope 医疗）
      - connection.py:1599  _direct_medical_chat()（医疗直连）

    因为 TTS 线程是 FIFO 单线程处理，MIDDLE 的 streaming_call 会先于紧随的
    LAST 完成；即使 streaming_call 因建连慢而 future.result(timeout) 超时，
    LAST 的 finish_session 仍会发送 FINISH 并关闭 ws，彻底消除孤儿任务。

    注：receiveAudioHandle.py 里另外两处恢复询问本就已正确配对（:225 无条件
    LAST、:261 显式 MIDDLE+LAST），未改动。

  验证
    - tests/test_asr_tts_interplay.py 新增 4 个用例：
        · 2 个覆盖 provider 对 LAST 的反应（[FIRST, MIDDLE, LAST] 必须下发
          FINISH；对照：缺 LAST 则不下发）；
        · 2 个直接驱动 connection.py 的 _enqueue_resume_query_tts，断言
          MIDDLE→LAST 成对、同 sentence_id、LAST 紧跟 MIDDLE。
      并做了变异验证：注释掉该方法里那条 LAST，这 2 个用例确实失败——证明
      测试对真正的改动有约束力（此前仅测 provider 反应，删掉 LAST 仍会通过）。
    - 中断/恢复相关全量：test_interrupt_resume.py、
      test_interrupt_resume_integration.py、test_answer_independence.py、
      test_closure_sid_filter.py、test_asr_tts_interplay.py 共 85 passed。
    - 全量 tests/：220 passed, 3 skipped, 4 failed。4 个失败经核对源码确认是
      既有的、与本次无关：3 个断言其它 provider（huoshan_double_stream /
      alibl_stream / aliyun_stream）源码尚未做同类重构，1 个是 ASR 测试自身
      fixture 缺陷；均不 import/执行 connection.py。
    - 独立代码审查代理结论：APPROVE（0 CRITICAL / 0 HIGH），无重复 LAST、
      无 client_abort / sentence_id 过滤 / report_on_last 副作用。

  待办（超出本次最小修复范围，供决定）
    - receiveAudioHandle.py:241-270 有一段不可达的重复恢复块（既有死代码），
      可删。
    - 可选：把恢复 MIDDLE 改到主 LAST 之前入队（receiveAudioHandle.py 已是此
      模式），可免去二次建连、无需补偿 LAST；但改动面更大，风险更高。
    - 恢复询问首次 streaming_call 建连的 10~15s 延迟（日志表现为空的
      「发送TTS文本失败:」）仍存在，语音最终会送达，仅影响响应速度。

------------------------------------------------

打断（abort）导致活动 TTS 会话孤儿化（第二类孤儿路径）

  现象
    上一节修完恢复询问后，仍偶发同一句 23s 报错，但**没有**
    「TTS合成器不存在，正在重建会话后继续发送文本」告警——说明不是恢复
    路径。logs/server.log 17:05:52 → 17:06:17 是一次复现：

      17:05:11  发送音频消息: SentenceType.LAST, None      ← 故事播完，收尾正常
      17:05:16  Abort message received → 保存"讲个故事"到恢复队列
      17:05:52  收到listen消息 state=detect text=继续 → chat("继续")
      17:05:54  Abort message received → 保存"继续"到恢复队列
      17:06:13  识别文本: 他有一个
      17:06:17  语音合成出现异常: task-failed request timeout after 23 seconds

    关键：17:06:17 往前 23 秒正是 17:05:54 的打断；整个窗口没有任何
    「收到打断信息，终止TTS文本处理线程」/「取消会话」日志，说明
    cancel_session() 从未被调用。

  根因（打断时活动会话不被收尾）
    abortHandle.handleAbortMessage 的处理顺序是：

      conn.client_abort = True
      conn.clear_queues()          ← 把 tts_text_queue 清空

    而 qwen_audio_tts_stream.tts_text_priority_thread 只在**取到消息**后
    才检查 client_abort 并调用 cancel_session()：

      message = self.tts_text_queue.get(timeout=1)
      ...
      if self.conn.client_abort: ... cancel_session() ... continue

    队列被 clear_queues() 清空后，线程再也取不到消息（一直走
    except queue.Empty: continue），于是永远走不到 cancel_session()，
    正在合成的会话（"继续"的 FIRST 已经 start_session 并 streaming_call
    提交了文本）无人收尾 → 空转 23 秒 → 服务端看门狗 task-failed。

    为什么平时不易察觉：通常打断后很快有新问题进来，新的 FIRST 会触发
    start_session()，内部先关闭上一个合成器，把孤儿会话顺手收掉；只有
    下一次 FIRST 在 23 秒之后才到时才暴露。

  修复（仅 core/providers/tts/qwen_audio_tts_stream.py）
    在 tts_text_priority_thread 的 except queue.Empty 分支里也检查打断状态，
    队列空闲时若处于打断且仍有活动会话，主动 cancel_session()：

      except queue.Empty:
          if self.conn.client_abort and self.synthesizer is not None:
              ... asyncio.run_coroutine_threadsafe(
                      self.cancel_session(self.conn.sentence_id), loop=...)
          continue

    cancel_session() 会下发 FINISH（streaming_cancel）并关闭 ws，随后把
    self.synthesizer 置 None，因此不会重复触发。这是对「线程取不到消息」这一
    确切缺口的补齐，与既有的「取到消息时检查打断」分支互补。

  验证
    - tests/test_asr_tts_interplay.py 新增
      TestAbortCancelsActiveSession：真实起事件循环 + TTS 线程，先 FIRST
      建立会话，再模拟 abortHandle（置 client_abort=True 并清空文本队列），
      断言线程在一个轮询周期内对会话下发 FINISH。
    - 变异验证：注释掉该 except queue.Empty 分支里的取消逻辑，本用例确实
      失败——证明测试对真正的改动有约束力。
    - 全量 tests/：221 passed, 3 skipped, 4 failed（同样是那 4 个既有无关失败）。

  备注（同类风险，未在本次范围）
    - 同样的「只在取到消息时检查打断」模式存在于 xunfei_stream、
      alibl_stream、aliyun_stream、huoshan_double_stream 等其它流式 TTS；
      其中 aliyun_stream 在打断时仅 continue、连 cancel 都没有。若换用这些
      provider，可能出现同样的 23s 孤儿。当前用户使用 qwen，故只修 qwen。
    - 更彻底的做法是在 abortHandle 里显式取消会话（provider 提供 cancel_session
      时调用），可一处覆盖多 provider；但会引入跨模块契约，本次未采用。

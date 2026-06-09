通过什么方式来区分，进入medical_pipeline与general_chat_pipeline

  Thought for 8s (ctrl+o to expand)

● 这是一个非常好的问题 — 意图分流是整个架构的核心决策点。让我给出一个完整的多级分流方案。

  ---
  管道分流核心：IntentRouterAgent 的 3 级级联路由

  分流不是"单一判断"，而是3 级漏斗，逐级降级，在延迟和准确率之间取得平衡：

  用户输入
      │
      ▼
  ┌─────────────────────┐
  │ Level 1: 关键词匹配 │  ← O(1) 哈希表查
  │   (10μs, 覆盖~60%)  │
  └─────────┬───────────┘
            │ 命中 → 直接返回路由结果 (含置信度)
            │ 未命中
            ▼
  ┌─────────────────────┐
  │ Level 2: 双塔向量   │  ← 轻量 Embedding 语义匹配
  │   (~80ms, 覆盖~30%) │
  └─────────┬───────────┘
            │ 命中且置信度 > 0.7 → 返回路由结果
            │ 置信度 0.4-0.7 或未命中
            ▼
  ┌─────────────────────┐
  │ Level 3: LLM 语义   │  ← 用极简 prompt 调用 LLM
  │   (~200ms, 覆盖~10%)│
  └─────────┬───────────┘
            │ 返回最终路由结果
            ▼
      路由完成 → 执行对应 Pipeline





  三级级联的具体实现

  Level 1: 关键词哈希匹配 (百微秒级)

  class KeywordRouter:
      """
      第一级: O(1) 哈希表关键词匹配
      覆盖日常约60%的请求，零模型调用
      """

      # 医疗关键词 — 使用集合实现 O(1) 查找
      MEDICAL_KEYWORDS = {
          # 饮食推荐
          "吃什么", "食谱", "忌口", "三餐", "营养", "饮食", "能吃吗",
          "不能吃", "主食", "蔬菜", "水果", "喝水", "饮水量",
          # 腹透问答
          "腹透", "透析", "腹膜透析", "管路", "换药", "护理",
          "并发症", "透析液", "超滤", "腹膜炎",
          # 体征咨询
          "血压", "血糖", "体重", "尿量", "水肿", "超滤量", "指标",
      }

      # 健康数据上报关键词
      HEALTH_KEYWORDS = {
          "上报", "记录", "我的...数据", "今天的...",
      }

      # IoT 控制关键词
      DEVICE_KEYWORDS = {
          "打开", "关闭", "调高", "调低", "播放", "暂停",
          "音量", "灯光", "开关",
      }

      @staticmethod
      def route(text: str) -> Optional[tuple[str, float]]:
          """关键词匹配路由，返回 (pipeline_name, confidence) 或 None"""
          for keyword in KeywordRouter.MEDICAL_KEYWORDS:
              if keyword in text:
                  # 细分医疗子意图
                  sub_intent = KeywordRouter._classify_medical(text)
                  return ("medical_pipeline", 1.0, sub_intent)

          for keyword in KeywordRouter.HEALTH_KEYWORDS:
              if keyword in text:
                  return ("health_data_pipeline", 1.0, None)

          for keyword in KeywordRouter.DEVICE_KEYWORDS:
              if keyword in text:
                  return ("device_control_pipeline", 1.0, None)

          return None  # 未命中，进入 Level 2

  Level 2: 双塔 Embedding 语义匹配 (数十毫秒)

  这一级解决关键词无法覆盖的场景，比如"最近感觉水肿有点厉害"→ 没有关键词但显然是医疗体征问题：

  class EmbeddingRouter:
      """
      第二级: 轻量 Embedding 语义匹配
      使用 all-MiniLM-L6-v2 做向量化，与预定义的"管道中心向量"做余弦相似度
      """

      def __init__(self):
          self.model = SentenceTransformer("all-MiniLM-L6-v2")

          # 预定义的管道语义中心向量 (每个管道由一组代表性句子描述)
          self.pipeline_centers = {
              "medical": self.model.encode([
                  "我今天吃什么对肾病好",
                  "腹透液怎么更换",
                  "我的血压正常吗",
                  "肌酐高了需要注意什么",
              ]).mean(axis=0),  # → shape: (384,)

              "general_chat": self.model.encode([
                  "你好啊",
                  "讲个笑话",
                  "今天天气怎么样",
                  "播放一首歌",
              ]).mean(axis=0),

              "health_data": self.model.encode([
                  "我要上报血糖数据",
                  "记录今天的体重",
                  "查询我的血压历史",
              ]).mean(axis=0),
          }

      def route(self, text: str) -> Optional[tuple[str, float]]:
          """语义匹配路由"""
          query_vec = self.model.encode([text])[0]  # (384,)

          max_sim = 0.0
          best_pipeline = None

          for pipeline_name, center_vec in self.pipeline_centers.items():
              sim = cosine_similarity(query_vec, center_vec)
              if sim > max_sim:
                  max_sim = sim
                  best_pipeline = pipeline_name

          # 置信度阈值判断
          if max_sim >= 0.7:
              return (f"{best_pipeline}_pipeline", max_sim)
          elif max_sim >= 0.4:
              return ("uncertain", max_sim)  # 需要 Level 3 确认
          else:
              return None  # 进入 Level 3

  Level 3: LLM 语义路由 (百毫秒级)

  只有前两级都搞不定时才走到这里，覆盖低频的边缘情况：

  class LLMRouter:
      """
      第三级: LLM 语义路由
      仅在关键词和 Embedding 都无法确定时调用
      使用极小 prompt + 低 max_tokens (只需输出管道名)
      """

      ROUTING_PROMPT = """分析用户意图，只返回管道名(一个词)：
  - medical: 医疗健康、饮食、腹透、体征相关问题
  - general_chat: 闲聊、问候、通用知识、天气、新闻
  - health_data: 体征数据上报、记录、查询
  - device_control: 设备控制、播放音乐、IoT指令

  用户: {user_input}
  意图类别:"""

      async def route(self, text: str) -> str:
          """LLM 路由 — 只需一个 token 即可确定"""
          prompt = self.ROUTING_PROMPT.format(user_input=text)

          # 调用最小模型 (甚至可以用 0.5B 级别的)
          response = await self.llm.response_no_stream(
              system_prompt="",
              user_prompt=prompt,
              max_tokens=5,  # 只输出一个词
              temperature=0,
          )

          pipeline = response.strip().lower()
          if pipeline in ["medical", "general_chat", "health_data", "device_control"]:
              return f"{pipeline}_pipeline"
          return "general_chat_pipeline"  # 默认降级

  实际生产中的落地方式

  在上述文件中我用了 IntentRouterAgent，它的实际实现就是三级级联的封装：

  class IntentRouterAgent(AgentBase):
      """
      三级别意图路由智能体
      """

      async def reply(self, msg: Msg) -> Msg:
          text = msg.content

          # Level 1: O(1) 关键词 (最快)
          result = KeywordRouter.route(text)
          if result:
              return Msg(self.name, {
                  "route": result[0],
                  "confidence": result[1],
                  "sub_intent": result[2] if len(result) > 2 else None,
                  "level": 1,
              })

          # Level 2: 向量语义
          result = EmbeddingRouter().route(text)
          if result and result[1] >= 0.7:  # 高置信度
              return Msg(self.name, {
                  "route": result[0],
                  "confidence": result[1],
                  "level": 2,
              })

          # Level 3: LLM 确认 (低置信度或未命中)
          result = await LLMRouter().route(text)
          return Msg(self.name, {
              "route": result,
              "confidence": 0.6,  # LLM 路由的固定置信度
              "level": 3,
          })

  与现有意图系统的兼容

  你的现有配置有 selected_module.Intent: function_call 或 intent_llm，迁移路径是：

  1. 新增 IntentRouterAgent 在前，做医疗/非医疗的"粗分类"
  2. 保留现有意图系统 在后面做"细分类"（具体调用哪个插件函数）
  3. 整个路由在 ConnectionHandler.chat() 中只替换最外层的 if/else 判断

  用户输入
      │
      ▼
  IntentRouterAgent (新增) ─── 三级级联判断
      │                          │
      ├── medical ────→ medical_pipeline (RAG + 医疗LLM)
      │
      ├── health_data → health_data_pipeline (数据上报)
      │
      └── general_chat ──→ 现有 chat() 逻辑 (function_call / intent_llm)
                                │
                                ▼
                           UnifiedToolHandler → 插件函数

  也就是说 general_chat_pipeline 的第一步就是调用现有 chat() 逻辑，现有功能完全不受影响。只有识别为 medical 时才走新的 RAG + 医疗LLM 流程。
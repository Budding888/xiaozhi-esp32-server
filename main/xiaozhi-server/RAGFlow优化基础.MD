# RAGFlow 检索分块（chunk）全字段详细释义
基于你提供的两条知识库检索片段，逐个拆解每个字段用途、业务含义，适配你的腹膜透析医疗知识库场景。

## 1. 基础文本字段
### `content`
文档切块后的**原文正文**，检索命中后供给大模型做RAG参考素材，完整保留PDF原文分段、标点、序号。
示例内容：腹膜透析中心CQI质量改进、腹膜炎并发症诊疗规范。

### `content_ltks`
分词/词袋拆分文本，全文切分单个关键词（英文转小写、剔除标点），用于**关键词检索、关键词相似度计算**。
作用：纯文本关键词匹配打分，弥补向量语义检索的不足。

### `document_keyword`
原始文档文件名，当前为《【医脉通•指南】腹膜透析标准操作规程（2010年出版）.pdf》，前端展示参考来源、溯源用。

## 2. ID 唯一标识类（主键，全系统唯一）
### `id`
当前文本分块（chunk）的唯一ID，每条切片独立id，用于区分同一PDF内不同段落。
### `document_id`
原始PDF文档唯一ID，同一文件下所有切片共用同一个`document_id`，可聚合整篇文档所有片段。
### `dataset_id`
知识库（数据集）唯一ID，多个PDF归属同一个知识库时共用`dataset_id`；用于隔离不同业务知识库。
### `image_id`
切片绑定的图片资源ID，PDF内带图表、流程图时存储图片关联标识；无图则仅文档基础前缀。
### `mom_id`
预留关联上级目录/文件夹ID，未使用时为空字符串。
### `row_id`
针对表格文档专用行号，纯文本PDF无表格则为`None`。

## 3. 相似度打分字段（RAG召回排序核心）
### `vector_similarity`
向量相似度（Embedding向量计算），取值0~1，数值越高语义越匹配；
第一条0.852、第二条0.846，代表两段文本和用户提问语义高度相关。

### `term_similarity`
关键词字面相似度，基于`content_ltks`分词匹配计算；
两条均0.06左右，说明用户提问关键词和原文字面重合度低，主要依靠向量语义匹配召回。

### `similarity`
综合加权总分，由`vector_similarity`+`term_similarity`加权融合得出，用于检索结果排序；
第一条0.3008，第二条0.2982，所以第一条排在前面。

## 4. 标签、关键词分类字段
### `important_keywords`
人工/算法提取的核心专业关键词数组，当前为空，未配置自动关键词提取。
### `tag_kwd`
文档自定义业务标签数组，可手动打标（如“腹透并发症”“质量管控”），当前无标签。
### `doc_type_kwd`
文档类型关键词，区分指南/病历/论文/化验单，本案例为空。

## 5. 坐标定位字段
### `positions`
PDF原文坐标数组，用于前端展示原文定位、高亮检索匹配段落；
每组 `[页码, 页面宽, 页面高, x起始, x结束, y起始, y结束]`，记录文字在PDF页面中的像素位置，支持跳转原文。

## 6. 补充业务逻辑总结
1. 召回排序逻辑：优先按 `similarity` 综合分降序展示；
2. 双重检索机制：
   - `vector_similarity`：语义模糊匹配（用户问同义、相近医疗术语也能召回）
   - `term_similarity`：精准关键词命中（完全相同词汇加分）
3. 层级关系：
`dataset_id`(知识库) > `document_id`(PDF文件) > `id`(文本切片chunk)
4. 业务用途：
- `content`：送入LLM作为参考资料；
- `document_keyword`：前端展示引用来源；
- `similarity/vector_similarity`：筛选低相关片段（可设置阈值过滤低分chunk）；
- `positions`：实现“点击跳转原文对应段落”功能。
---

=================================================================================================


# /api/v1/retrieval 检索接口完整全量解读
## 一、接口基础信息
- 作用：单独执行知识库检索，仅返回匹配文档片段（Chunk），不调用大模型；可用于RAG前置召回、手动筛选参考资料。
- 请求方式：`POST`
- 编码：`Content-Type: application/json`
- 鉴权：`Authorization: Bearer {API_KEY}`

## 二、核心混合相似度加权规则（关键）
文档明确权重约束：
1. `vector_similarity_weight` = 向量余弦相似度权重，记为 `w`
2. 关键词字面相似度权重 = `1 - w`
3. 混合总分公式：
$$
similarity = w \times vector\_similarity + (1-w) \times term\_similarity
$$
4. 两权重相加恒等于1，值域0~1；
5. 默认值：`vector_similarity_weight=0.3`
   - 向量权重0.3，关键词权重0.7
6. `similarity_threshold` 混合总分阈值，默认0.2
   - 混合分 ＜ 0.2：直接过滤丢弃，不返回该文本块
   - 混合分 ≥ 0.2：保留参与分页、排序

### 结合你之前的数据验算示例
向量相似度=0.85228944，关键词相似度=0.064454946，默认w=0.3
$$
0.3 \times 0.85228944 + 0.7 \times 0.064454946
= 0.255686832 + 0.0451184622
= 0.3008052942
$$
和你日志里 `similarity:0.3008052942` 完全对应，验证公式无误。

## 三、全部请求参数逐字段释义
### 必传参数二选一
1. `question` string 必填
用户检索提问，用于向量编码、关键词匹配。
2. `dataset_ids` list[string] / `document_ids` list[string] 二选一
- `dataset_ids`：知识库ID列表，检索整个知识库下所有文档；
- `document_ids`：指定单/多篇文档ID，仅检索指定文件；
限制：同一批document必须使用相同Embedding模型，否则报错。

### 分页控制
1. `page` int 默认1：当前页码
2. `page_size` int 默认30：每页最多返回多少chunk

### 检索相似度核心参数
1. `similarity_threshold` float 默认0.2
混合相似度最低门槛，低于该值直接过滤。
2. `vector_similarity_weight` float 默认0.3
向量语义权重，关键词权重自动为 `1 - 该值`；
医疗场景建议0.3~0.4，侧重语义匹配。
3. `top_k` int 默认1024
向量库初次召回数量：先从向量库取出top_k个最相似chunk，再计算混合分、过滤阈值，再分页输出。
> top_k越大召回候选越多，但检索速度变慢。

### 关键词检索控制
`keyword` boolean 默认false
- true：开启关键词检索（依托content_ltks分词计算term_similarity）；
- false：仅向量检索，term_similarity=0，混合分=向量分。

### 展示辅助参数
1. `highlight` boolean 默认false
true：返回结果中高亮命中关键词文本。
2. `cross_languages` list[string]
多语言关键词检索，自动翻译query做跨语言匹配。

### 重排Rerank
`rerank_id` string
传入重排模型ID，开启后会用Rerank分数替代原有混合相似度做排序，大幅提升检索精准度。

### 知识图谱/目录增强
1. `use_kg` boolean 默认false
开启知识图谱多跳检索，需知识库已构建图谱。
2. `toc_enhance` boolean 默认false
基于文档目录增强检索，需提前提取TOC目录。

### 元数据过滤 `metadata_condition` 对象
在检索完成后，按文档自定义元数据二次过滤，支持多条件组合：
- `logic`：and（全部满足）/or（任意满足）
- `conditions[]` 单条过滤条件：
  - name：元数据字段名（author、url、科室等）
  - comparison_operator 运算符：contains / not contains / = / ≠ / > / < / empty / not empty
  - value：对比值

## 四、完整curl调用示例拆解
```bash
curl --request POST \
     --url http://127.0.0.1:8008/api/v1/retrieval \
     --header 'Content-Type: application/json' \
     --header 'Authorization: Bearer ragflow-xxx' \
     --data '
     {
          "question": "腹膜透析中心CQI质量改进怎么做",
          "dataset_ids": ["1902efec663111f1a4fda54dc13d4fe0"],
          "similarity_threshold":0.2,
          "vector_similarity_weight":0.35,
          "top_k":512,
          "keyword":true,
          "page":1,
          "page_size":10
     }'
```
含义：
在指定腹透指南知识库检索，向量权重0.35、关键词权重0.65，最低混合分0.2，初次召回512条候选，开启关键词匹配，第一页返回10条片段。

## 五、业务调优建议（你的腹膜透析医疗知识库）
1. 同义专业术语多（残余肾功能、腹透相关腹膜炎）
调高 `vector_similarity_weight=0.35~0.4`，偏重语义匹配；
2. 需要精准匹配专有名词（PDCA、KPI、腹膜炎）
调低向量权重至0.25，关键词权重0.75；
3. 减少无关片段干扰
提高 `similarity_threshold=0.22~0.25`，过滤低分噪声chunk；
4. 追求检索精度
配置 `rerank_id` 开启重排模型，替换混合相似度排序；
5. 大批量检索提速
调低 `top_k=256/512`，无需1024候选池。

## 六、检索完整执行流程
1. 对question做Embedding，向量库召回top_k条候选chunk；
2. 开启keyword时，分词计算每条term_similarity；
3. 按公式计算混合 `similarity`；
4. 过滤掉混合分 < similarity_threshold 的chunk；
5. 有rerank则使用重排分数重新排序，否则按混合分降序；
6. 按page、page_size分页截断返回结果。
---

===============================================================================================


# vector_similarity、term_similarity、similarity三个字段逐句解释 + 套公式验算
## 1. vector_similarity: 0.84633327
**向量余弦相似度**
把你的提问和文档块分别转成Embedding向量，计算语义相似度，值域 0～1。
数值越高 = 语义意思越接近。
0.846 属于很高的语义匹配度，说明这段文字和你问的问题核心内容高度贴合。

## 2. term_similarity: 0.06335368969828364
**关键词字面匹配相似度**
基于文档分词 `content_ltks`，统计你提问里的词语和原文词语重合程度。
0.06 很低，代表：你的提问用词和原文文字重合很少，只是意思相近、字面关键词对不上。

## 3. similarity: 0.2982475637887986
**混合综合相似度（最终排序、过滤阈值用的总分）**
接口规则固定公式：
`similarity = vector_similarity × w + term_similarity × (1 - w)`
默认权重 `vector_similarity_weight=0.3`，关键词权重 = 1 - 0.3 = 0.7

### 代入数值验算
```
向量部分得分：0.84633327 × 0.3 = 0.253899981
关键词部分得分：0.06335368969828364 × 0.7 = 0.04434758278879855
综合总分：0.253899981 + 0.04434758278879855 = 0.298248
```
和你给出的 `similarity: 0.2982475637887986` 完全一致。

## 业务逻辑总结
1. 这段文档**语义高度匹配**，但文字关键词重合很少；
2. 系统默认权重更看重关键词匹配（0.7）、轻量语义（0.3），拉低了综合总分；
3. 综合分 0.298 大于默认阈值 0.2，所以不会被过滤，正常召回展示；
4. 如果想让语义占比更高，调用检索接口时调高 `vector_similarity_weight`（如0.35/0.4），综合分会同步上升。
---


====================================================================================================


# 医疗知识库 RAG 三个相似度参数配置与优化方案
## 前置回顾公式
混合相似度：
$$similarity = w_{vec} \times vector\_similarity + (1-w_{vec}) \times term\_similarity$$
- $w_{vec}$：`vector_similarity_weight` 向量权重
- $1-w_{vec}$：关键词字面匹配权重
- `similarity_threshold`：混合分最低过滤门槛，低于该值直接丢弃片段

医疗文本特点：
1. 大量专业同义术语：残余肾功能/RRF、腹膜透析/PD、贫血纠正达标率，字面文字不一样但语义完全相同；
2. 专有名词精准匹配有价值：腹膜炎、隧道感染、PDCA、KPI，命中关键词可信度更高；
3. 长指南、病历段落易出现低关键词重合、高语义相似的chunk；
4. 噪声多：无关并发症、其他病种内容容易被向量弱召回。

# 一、向量权重 vector_similarity_weight 分场景配置
## 场景1：通用腹透科普问答（绝大多数业务场景，推荐）
**配置：vector_similarity_weight = 0.38 ~ 0.4**
向量权重0.4，关键词权重0.6
### 适配理由
1. 优先识别医疗同义术语，解决“用词不一样但是同一个问题”召回不到的问题；
2. 保留关键词60%权重，完全漏掉专业名词的无关文本不会排名靠前；
### 示例收益
用户问「残余肾功能有什么作用」，原文只写「RRF对透析患者的价值」，term_similarity极低，但向量分会拉高综合分，正常召回。

## 场景2：精准检索专有名词、化验单、诊断标准（严格匹配术语）
**配置：vector_similarity_weight = 0.25 ~ 0.3**
向量权重0.3，关键词权重0.7（系统默认值）
### 适配理由
优先字面关键词命中，避免把无关同类疾病内容召回；
例如搜索「出口处感染」，不会大量推送腹膜炎通用内容。

## 场景3：长病历、模糊问诊、患者口语化提问（病人大白话提问）
**配置：vector_similarity_weight = 0.45 ~ 0.5**
向量权重0.5，关键词权重0.5
### 适配理由
患者口语和指南书面文字关键词几乎无重合，完全依靠语义向量召回；
例：患者说“透析完肚子疼”，原文写“腹膜透析相关腹痛并发症处理”。

## 禁止配置
不要超过0.6：关键词权重过低，大量语义相近但完全无关的医疗文档混入上下文，干扰大模型判断；

# 二、相似度阈值 similarity_threshold 优化
默认0.2，医疗场景分三档调整
## 1. 严格模式（生产线上，推荐）
`similarity_threshold = 0.22 ~ 0.25`
适用：对外问答、语音TTS问答、RAG流式接口
作用：过滤低分弱相关片段，减少无关医疗文本进入LLM上下文，避免模型混淆病种、输出错误医疗信息；
结合你现有数据：综合分0.298、0.300均可正常保留，极低分0.2以下噪声直接剔除。

## 2. 宽松模式（内部查阅、知识库调试）
`similarity_threshold = 0.18 ~ 0.2`
适用：知识库不全、文档少、测试检索效果；
缺点：会带入大量弱相关片段，增加模型混淆风险，**不建议线上使用**。

## 3. 极严格模式（专科精准查询，如并发症专项）
`similarity_threshold = 0.26 ~ 0.3`
适用：只需要高度匹配的指南原文，不需要近似参考；
适合：查询诊断标准、指标达标值、手术规范。

# 三、term_similarity 配套开关控制（keyword 参数）
接口 `keyword: true/false`
1. `keyword: true`（默认开启，医疗必须开）
开启分词关键词匹配，计算term_similarity，字面专业名词会加权加分；
2. `keyword: false`
不计算关键词相似度，term_similarity恒等于0，混合分=向量分；
仅适合纯口语模糊问诊，常规医疗业务禁用。

# 四、配套辅助参数协同优化（提升检索质量）
1. top_k 向量候选池
线上生产：`top_k=512`，不用默认1024，减少检索耗时，足够医疗知识库召回；
知识库文档上万：可调至768。

2. 开启 Rerank 重排（医疗场景强烈推荐）
填入`rerank_id`后，会抛弃混合相似度，使用重排模型打分排序，区分细微医疗语义差异；
解决痛点：向量相似但病种无关的文本排名靠前问题。

# 五、三套可直接落地的完整参数模板
## 模板1：线上标准腹透问答（推荐，平衡语义+关键词）
```json
{
  "question": "xxx",
  "dataset_ids": ["xxx"],
  "similarity_threshold": 0.23,
  "vector_similarity_weight": 0.4,
  "keyword": true,
  "top_k": 512,
  "page_size": 10
}
```

## 模板2：专科精准检索（指标、诊断、手术规范）
```json
{
  "similarity_threshold": 0.28,
  "vector_similarity_weight": 0.3,
  "keyword": true,
  "top_k": 512
}
```

## 模板3：患者口语模糊提问（语音交互场景）
```json
{
  "similarity_threshold": 0.22,
  "vector_similarity_weight": 0.48,
  "keyword": true,
  "top_k": 768
}
```

# 六、调优判断标准（怎么判断参数是否合适）
1. 正常效果
- 同义医疗术语可以召回；
- 完全无关其他病种文档不会进入top10；
- 综合分低于0.22的无关片段全部过滤。

2. 问题&调整方案
- 现象1：专业术语搜不到同义指南
  调高 `vector_similarity_weight`（+0.05）
- 现象2：大量无关疾病内容混入参考资料
  1. 提高 `similarity_threshold`；
  2. 降低向量权重；
  3. 开启Rerank重排。
- 现象3：患者口语提问召回为空
  调高向量权重、略微降低阈值至0.20。
---


===========================================================================================

# 三者完整关系拆解（结合RAGFlow官方公式+医疗场景直观理解）
## 1、基础公式（决定权重大小约束）
```
关键词权重 term_weight = 1 - vector_similarity_weight
混合总分 = vector_similarity_weight × vector_similarity + term_weight × term_similarity
```
### 权重硬性约束
1. 两个权重相加永远 = 1；
2. `vector_similarity_weight` 取值范围：0 ~ 1；
3. 关键词权重随向量权重反向变化：
   - 向量权重变大 → 关键词权重同步变小
   - 向量权重变小 → 关键词权重同步变大

举例：
- vector_similarity_weight=0.3 → 关键词权重=0.7
- vector_similarity_weight=0.4 → 关键词权重=0.6
- vector_similarity_weight=0.5 → 关键词权重=0.5
- vector_similarity_weight=0.25 → 关键词权重=0.75

## 2、向量权重 & 关键词权重 大小关系带来的业务影响
### 情况A：向量权重 < 关键词权重（默认0.3 vs 0.7）
关键词占主导，检索更看重**文字字面匹配**
- 优点：精准命中腹膜炎、残余肾功能、PDCA等专有名词，不容易混入跨病种无关文档
- 缺点：患者口语、医学同义词召回弱，提问和指南文字不一样就容易低分过滤

### 情况B：向量权重 > 关键词权重（0.4/0.45/0.5）
语义向量占主导，检索更看重**意思相近**
- 优点：适配医疗同义术语、患者大白话提问，语义相近的文档能正常召回
- 缺点：容易召回语义近似但病种无关的文本，干扰大模型

### 情况C：两者相等（0.5=0.5）
语义、关键词各占一半，平衡口语提问和专业名词检索。

## 3、相似度阈值 similarity_threshold 和两个权重的关系
阈值是**过滤门槛**，和权重无数学计算关联，但两者互相配合、互相制约：
1. 权重只改变「混合总分高低」；阈值决定「这条chunk留不留」
2. 同样一段文本，调高向量权重，混合总分会上升，更容易超过阈值被保留；
3. 同样一段文本，调低向量权重，混合总分会下降，更容易低于阈值被过滤。

### 直观例子（你现有数据）
vector_similarity=0.846，term_similarity=0.063
- 向量权重0.3，关键词0.7 → 综合分≈0.298
  阈值0.2、0.22、0.25 都会保留；阈值0.3则直接过滤
- 向量权重调到0.4，关键词0.6 → 综合分≈0.376
  哪怕阈值0.3也能正常召回

### 联动调优逻辑
1. 调高向量权重（侧重语义）→ 混合分普遍变大 → 建议同步**提高阈值**，过滤弱相关噪声；
2. 调低向量权重（侧重关键词）→ 混合分普遍变小 → 建议**降低阈值**，避免同义有用文档被误过滤；

## 4、三者联动搭配总结（医疗腹透场景）
| 配置方向 | vector权重 | 关键词权重 | 推荐阈值 | 适用场景 |
|--------|-----------|-----------|---------|---------|
| 精准术语优先 | 0.25~0.3 | 0.7~0.75 | 0.24~0.28 | 查诊断标准、指标、手术规范 |
| 平衡通用问答 | 0.38~0.4 | 0.6~0.62 | 0.22~0.23 | 线上常规患者科普（主推） |
| 口语模糊提问 | 0.45~0.5 | 0.5~0.55 | 0.20~0.22 | 语音TTS、患者大白话问诊 |

## 5、核心规律一句话总结
1. 向量权重与关键词权重**此消彼长，总和固定为1**；
2. 向量权重越大，语义对总分影响越强，文档更容易被召回；
3. 相似度阈值是固定筛选线，权重改变总分高低，阈值决定最终是否保留片段，两者需要配套调整。
---
---
---

# 医疗问答进度TTS播报优化记录

## 背景

在医疗问答流程（`search_medical_question`）中，处理链路涉及：
1. Query改写（MedicalQwen LLM调用）
2. RAGFlow知识库检索（HTTP请求，超时可达50秒）
3. 知识库内容压缩（通用LLM调用）
4. MedicalQwen推理（LLM流式推理）

整条链路耗时10~50秒，用户在此期间听到静音，体验差。需添加语音进度播报。

## 改动内容

### 1. `search_medical_question.py` — 新增进度TTS

新增 `_send_progress_tts(conn, text)` 辅助函数，在编排器各阶段插入进度播报：

- 阶段0（立即确认）：`"好的，正在为您检索关于{question}有关的回答，请稍候。"`
- 阶段1（开始检索）：`"正在检索知识库，请稍候。"`
- 阶段2（检索完成，结果呈现）：`"抱歉，让您久等了。这是为您查询到的结果。"`

同时移除原 `final_medical_answer` 前缀中的尴尬客套话（"不还意思，我进行了大量思考..."），让对话记录更干净。

### 2. `connection.py` — 修复 `_direct_medical_chat` 缺少FIRST标记

`_direct_medical_chat()` 成功路径未发送 `SentenceType.FIRST`，导致 TTS 流无法正确启动。添加了 FIRST 标记。

## 遇到的问题：进度消息播报不完整

### 现象

用户提问后，只有阶段0的 `"好的，正在为您检索关于...的回答，请稍候"` 能听到声音，阶段1和阶段2的进度消息都没有语音播报。

### 排查过程

追踪 TTS 引擎 `core/providers/tts/base.py` 中的 `tts_text_priority_thread` 和 `_get_segment_text()` 方法。

### 根因分析

TTS 引擎有一个**文本分段缓冲机制**，核心逻辑在 `_get_segment_text()`：

```python
def _get_segment_text(self):
    full_text = "".join(self.tts_text_buff)
    current_text = full_text[self.processed_chars :]

    # 根据是否是第一句话选择不同的标点符号集合
    punctuations_to_use = (
        self.first_sentence_punctuations   # ("，", "~", "、", ",", "。", "？", ...)
        if self.is_first_sentence
        else self.punctuations             # ("。", "？", "?", "！", "!", "；", ";", "：")
    )

    # 在 current_text 中查找匹配的标点符号
    for punct in punctuations_to_use:
        pos = current_text.rfind(punct)
        ...

    if last_punct_pos != -1:
        segment_text_raw = current_text[: last_punct_pos + 1]
        # → 找到句末标点，切分并立即合成语音
        return segment_text

    elif self.tts_stop_request and current_text:
        # → 收到停止信号，强制输出剩余文本
        return current_text
    else:
        return None  # ← 找不到句末标点，文本被缓冲等待后续内容
```

- **第一句**（`is_first_sentence = True`）使用 `first_sentence_punctuations`，包含中文逗号 `"，"`，所以遇到逗号就会切分
- **后续句子**（`is_first_sentence = False`）使用 `self.punctuations`，**仅包含句末标点** `"。？！；："`，不含 `"，"`

**问题重现**：

原始进度消息：
- `"好的，正在为您查询医疗知识库，请稍候"` → 第一句匹配 `"，"` 切分出前段 `"好的，正在为您查询医疗知识库，"`，但剩余 `"请稍候"` 无句末标点 → **进入缓冲**
- `"正在检索知识库..."` → 无句末标点 → **持续缓冲**
- `"抱歉，让您久等了，这是为您查询到的结果"` → 只有逗号，无句末标点 → **继续缓冲**
- 直到 MedicalQwen 流式输出产生 `"。"` 时，所有缓冲文本 + 答案前段才合并成一大块输出

**结果**：用户只听到第一句逗号前的半截语音，其他进度消息无声。

### 修复方案

给每一条进度消息末尾添加句号 `"。"`（`self.punctuations` 中包含的标点）：

| 消息 | 修改前（缓冲） | 修改后（立即合成） |
|------|---------------|-------------------|
| 阶段0 | `"请稍候"` | `"请稍候。"` |
| 阶段1 | `"正在检索知识库，请稍候"` | `"正在检索知识库，请稍候。"` |
| 阶段2 | `"这是为您查询到的结果"` | `"这是为您查询到的结果。"` |

### 核心规律

通过TTS引擎 `_send_progress_tts()` 发送的进度文本，**必须包含 `self.punctuations` 集合中的句末标点（`。？！；：`）**，否则 `_get_segment_text()` 返回 `None`，文本被缓冲至下一个句末标点出现才输出。

涉及文件：
- `plugins_func/functions/search_medical_question.py` — 进度TTS消息内容
- `core/providers/tts/base.py` — TTS文本缓冲/分段机制（`_get_segment_text` 第392~429行）
- `core/connection.py` — `_direct_medical_chat` FIRST标记修复



















































# 简历项目描述

## 项目名称

PaiSmart-mini：企业知识库 RAG 问答系统

## 一句话介绍

基于 FastAPI、LangChain、Chroma 和大模型 API 实现的企业知识库 RAG 系统，支持文档上传、解析切分、向量化入库、BM25 + 向量混合检索、SSE 流式问答、多会话历史和引用溯源。

## 技术栈

FastAPI、SQLAlchemy、MySQL、LangChain、Chroma、BM25、jieba、PyMuPDF、DeepSeek API、SiliconFlow Embedding API、SSE

## 简历版描述

- 设计并实现企业知识库 RAG 系统，覆盖文档上传、文本解析、递归切分、Embedding 向量化、Chroma 入库、检索问答和引用溯源完整链路。
- 基于 FastAPI `BackgroundTasks` 实现文档后台解析，结合 `status` 和 `error_message` 字段追踪文档处理状态，支持失败原因记录和后续重建。
- 封装 `EmbeddingProvider` 统一文档向量化和查询向量化，避免入库和检索使用不同 embedding 模型导致向量空间不一致。
- 基于 Chroma 实现向量检索，并引入 BM25 关键词检索，通过 RRF 对两路检索结果进行融合，提升专有名词和技术缩写场景下的召回稳定性。
- 实现 SSE 流式问答接口，模型生成过程中以 `chunk` 事件增量返回，结束后以 `done` 事件返回完整回答和 references。
- 将历史记录从文件存储升级为数据库存储，设计 `conversation_sessions` 和 `conversation_messages` 两张表，支持用户多会话、历史消息加载和引用保存。
- 实现 RAG 自动评估脚本，统计文档命中率、MRR、关键词覆盖率、引用证据覆盖率、引用准确率和无关问题拒引率，并支持按 Redis、论文、负例等 case 分组统计。
- 对 PDF 解析文本进行清洗，修复 `R e d i s`、`A O F`、`I O` 等字符拆散问题，并通过完整重建文档让清洗逻辑重新作用于 chunk 和向量库。

## 面试展开版

这个项目主要分两条核心链路。

第一条是知识入库链路：用户上传文档后，后端校验文件类型，通过分块读取文件流计算 MD5 做文档级去重，然后保存原始文件并在 documents 表中创建记录。解析任务通过 FastAPI `BackgroundTasks` 后台执行，根据文件类型进行 TXT 或 PDF 解析，解析后先做文本清洗，再用 `RecursiveCharacterTextSplitter` 进行递归切分。切分后的 chunk 保存到 `document_chunks` 表，随后调用统一的 embedding provider 批量生成向量，并写入 Chroma，同时回写 vector_id。流程成功后文档状态改为 completed，失败时回滚数据库事务并记录 error_message。

第二条是流式问答链路：用户提问后，系统根据 user_id 和 session_id 从数据库读取历史消息，并转换成 LangChain 需要的 `HumanMessage` / `AIMessage` 格式。随后通过 `hybrid_search` 执行混合检索，向量检索负责语义召回，BM25 负责关键词召回，两路结果通过 chunk_id 去重并用 RRF 融合排序。检索结果一方面格式化成 context 放入 prompt，另一方面构造成 references 用于前端展示和数据库保存。模型通过 stream 方式生成回答，后端用 SSE 分片返回，最后保存本轮用户问题、助手回答和引用信息。

## 可量化亮点

- 支持 48 条 RAG eval case，覆盖 Redis、论文、负例和 hard case。
- 引入 MRR 指标，区分正确文档排第 1 位和排第 5 位的体验差异。
- 支持分组评估，能定位不同文档类型上的检索问题。
- 对比清洗前后结果，Redis 文档引用证据关键词覆盖率明显提升。

## 项目边界

当前版本重点实现 RAG 核心链路和评估体系，尚未完整实现企业级用户权限、组织隔离、MinIO、分片上传、rerank 和任务队列。这些能力已列入后续 roadmap。

## 面试官可能关注的点

- 为什么需要 chunk metadata？
- 为什么 Chroma score 和 BM25 score 不能直接相加？
- 为什么流式场景要手动保存 history 和 references？
- 为什么重新向量化不等于完整重建文档？
- 为什么 error_message 字段对后台任务很重要？
- 为什么 RAG 需要评估脚本，而不是只看回答是否通顺？

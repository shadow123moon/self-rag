# 面试讲稿

## 1. 项目整体介绍

我做的是一个企业知识库 RAG 问答系统，项目名叫 PaiSmart-mini。它的核心目标是把企业文档上传到系统中，经过解析、切分、向量化后形成知识库，用户提问时系统会检索相关文档片段，并结合历史对话和引用资料，让大模型生成回答。

这个项目主要有两条核心链路：

第一条是文档上传入库链路，负责把文件转换成可检索的 chunk 和向量。

第二条是流式对话问答链路，负责根据用户问题读取历史、检索资料、拼 prompt、流式生成回答，并保存对话历史和引用来源。

## 2. 文档上传后发生了什么？

用户上传文件后，后端首先校验文件类型，只允许支持的格式。然后使用 `await file.read(8192)` 分块读取上传文件流，同时计算文件 MD5。MD5 用于文档级去重，避免重复上传同一个文件。

文件保存到本地后，系统会创建 documents 表记录，包含 document_id、文件名、文件路径、文件 MD5、文件大小、状态、chunk_count、error_message、创建时间和更新时间。

文档记录创建后，解析任务不会阻塞上传接口，而是通过 FastAPI 的 `BackgroundTasks.add_task()` 放到后台执行。后台任务根据 document_id、file_path 和 file_type 重新读取原始文件，进入解析流程。

## 3. 文档解析和切分怎么做？

TXT 文件读取后得到一个完整字符串，PDF 文件目前使用 PyMuPDF 按页解析，每页得到一个字符串，因此 PDF 可以保留 page_number。

解析后会先进入 `clean_text()` 文本清洗，处理 PDF 抽取时常见的脏文本，比如把 `R e d i s` 合并成 `Redis`，把 `A O F` 合并成 `AOF`，避免影响 BM25 和 embedding。

切分使用 LangChain 的 `RecursiveCharacterTextSplitter`。它会根据 separators 从大到小递归切分文本，比如先按段落，再按换行、句号、空格等切分。如果切出来的片段仍然超过 chunk_size，就继续使用更小粒度的分隔符。chunk_overlap 用来保留相邻 chunk 的重叠内容，减少语义在边界处被切断。

切好的 chunk 会保存到 `document_chunks` 表，字段包括 chunk_id、document_id、chunk_index、content、page_number、source 和 vector_id。

## 4. 向量化和 Chroma 入库怎么做？

我把 embedding 能力封装成了 `EmbeddingProvider`，里面有两个核心方法：

- `embed_texts()`：用于批量把文档 chunk 转成向量。
- `embed_query()`：用于把用户问题转成查询向量。

这样文档入库和问题查询使用的是同一个 embedding 模型，避免向量空间不一致。

向量生成后，`vector_service` 会把 chunk 内容、metadata 和 embedding 写入 Chroma。metadata 里保存 chunk_id、document_id、filename、page_number 等信息。

metadata 很关键，它不是主要给模型看的，而是给系统做去重、引用展示和调试用的。例如混合检索中 BM25 和向量检索可能命中同一个 chunk，这时就靠 chunk_id 做去重和分数融合。

## 5. 为什么要完整重建文档？

如果只是 embedding 模型变了，可以重新向量化，也就是使用已有 chunk 重新生成 embedding。

但如果 parser、clean_text 或 splitter 逻辑发生变化，只重新向量化是不够的。因为旧的 `document_chunks.content` 还是旧文本，比如里面可能仍然是 `R e d i s`。这时必须完整重建文档：删除旧向量、删除旧 chunks、重新解析、重新清洗、重新切分、重新向量化。

所以我区分了 `reindex` 和 `rebuild`：

- `reindex`：chunk 内容不变，只重新生成向量。
- `rebuild`：重新解析和切分，适用于解析或切分逻辑变更。

## 6. 流式对话为什么要自己组装 history 和 context？

最开始可以使用 `RunnableWithMessageHistory` 自动管理历史，但流式 RAG 场景下需要更强的业务控制。

原因有三点。

第一，流式生成不是一次性得到完整答案，而是模型一点点输出 token。我需要一边把 token 通过 SSE 返回给前端，一边累计 full_answer，等生成结束后再保存完整 assistant 消息。

第二，一次回答不只保存 content，还要保存 references。references 来自本次检索结果，`RunnableWithMessageHistory` 默认不知道这些业务 metadata。

第三，history 和 context 来源不同。history 来自数据库历史消息，context 来自本次知识库检索结果。手动组装 payload 更清楚：

```python
payload = {
    "history": history,
    "context": context,
    "input": query,
}
```

## 7. 历史记录怎么保存？

历史记录用两张表。

`conversation_sessions` 保存会话级信息，比如 session_id、user_id、title、status、created_at、updated_at。

`conversation_messages` 保存消息级信息，比如 message_id、session_id、user_id、role、content、references_json 和 created_at。

读取历史时，系统根据 user_id 和 session_id 查询消息记录，然后根据 role 转换成 LangChain 需要的 `HumanMessage`、`AIMessage` 或 `SystemMessage`。这样才能塞给 `MessagesPlaceholder("history")`。

## 8. 混合检索怎么做？

混合检索包括两路。

第一路是 Chroma 向量检索：

```python
search_similar_with_score(query, top_k)
```

它返回 `list[(Document, score)]`。这里的 score 在当前配置下是 distance，越小越相关。

第二路是 BM25 关键词检索。系统从 `document_chunks` 表加载所有 chunk，用 jieba 对 chunk 内容分词，然后用 `BM25Okapi` 构建关键词检索器。查询时对 query 分词，通过 `get_scores()` 得到每个 chunk 的 BM25 分数。BM25 分数越大越相关。

由于 Chroma distance 和 BM25 score 不是同一个分数体系，而且方向也不同，所以不能直接相加。我使用 RRF 做融合。RRF 不看原始分数，只看各自排名：

```python
1 / (rrf_k + rank + 1)
```

如果同一个 chunk 同时被向量检索和 BM25 命中，就通过 chunk_id 去重，并把两路 RRF 分数叠加。最后按 hybrid_score 排序，返回 top_k。

## 9. SSE 流式输出怎么实现？

接口是：

```text
POST /api/chat/stream
```

后端返回 `StreamingResponse`，media type 是：

```text
text/event-stream
```

`rag_service.stream_answer()` 是一个 generator。模型每生成一个 token，就 yield：

```json
{"type": "chunk", "content": "..."}
```

router 再把它包装成 SSE 格式：

```text
data: {"type":"chunk","content":"..."}
```

生成结束后，后端保存历史和引用，然后返回：

```json
{"type": "done", "answer": "...", "references": [...]}
```

前端根据 `chunk` 事件实时追加内容，根据 `done` 事件更新引用和会话状态。

## 10. RAG 评估怎么做？

我写了 `eval/eval_rag.py`，用 JSON 维护测试用例。每个 case 包含 question、expected_documents、expected_keywords、expected_reference_keywords 和 should_have_references。

评估脚本会逐题调用 RAG 流程，收集 answer 和 references，然后计算：

- 文档命中率：是否检索到了预期文档。
- MRR：正确文档排在第几位。
- 平均关键词覆盖率：回答里是否覆盖预期关键词。
- 引用证据关键词覆盖率：references 的内容是否包含证据关键词。
- 引用预期准确率：该引用时是否引用，不该引用时是否拒引。
- 平均引用精确率：返回的 references 中有多少来自预期文档。
- 无关问题拒引率：负例问题是否没有引用。

我还加了分组统计，比如 redis、pft、amef、negative、hard，可以定位是哪一类文档或问题拖累整体指标。

## 11. 项目中踩过的坑

第一，Chroma 的 score 在当前配置下是 distance，越小越相关，而 BM25 score 越大越相关，不能直接相加。

第二，修改 `clean_text()` 后，旧数据库 chunk 不会自动变化，必须完整 rebuild 文档，否则引用里还是旧脏文本。

第三，数据库 rollback 只能回滚数据库，不能自动回滚 Chroma，所以删除和重建时要特别注意数据库和向量库一致性。

第四，流式生成时不能在每个 token 都保存数据库，必须累计完整答案，生成结束后再保存本轮 user 和 assistant 消息。

第五，metadata 对 RAG 系统非常关键。page_content 是给模型看的，metadata 是给系统做引用、去重、调试和权限过滤用的。

## 12. 如果继续优化会做什么？

短期会接入 Docling 作为可选 PDF parser，改善英文论文、表格和公式场景的解析质量。

检索层会继续尝试 rerank，对 hybrid_search 的候选结果进行重排序。

工程层会补知识库隔离、用户权限、MinIO 文件存储、大文件分片上传、任务队列和 WebSocket。

如果做 Agent 扩展，会把知识库检索、文档列表、文档 chunk 查询包装成工具，让模型能基于工具调用完成多步任务。

---

## 13. 为什么选 Chroma？和其他向量数据库有什么区别？

Chroma 是轻量级嵌入式向量数据库，部署简单，不需要额外依赖，适合快速验证 RAG 链路。项目初期数据量小，Chroma 够用。

| 向量数据库 | 定位 | 和 Chroma 的区别 |
|-----------|------|-----------------|
| Chroma | 轻量嵌入式，适合原型和小项目 | 本地文件存储，部署简单 |
| Milvus | 分布式，生产级，支持亿级向量 | 部署重（依赖 etcd/MinIO），但支持水平扩展 |
| Pinecone | 全托管 SaaS，不用自己部署 | 按调用量付费，数据在别人服务器上 |
| Weaviate | 支持混合检索（向量+关键词内置） | 内置 BM25，不用自己写 hybrid_search |
| Qdrant | Rust 实现，性能好 | 支持按 payload 过滤，适合带条件的检索 |

Chroma 的局限：不支持分布式，单机性能有上限。如果数据量大了需要换 Milvus 或 Qdrant。

---

## 14. RRF 融合的原理是什么？为什么选 RRF 而不是加权求和？

BM25 分数是越大越相关，向量距离是越小越相关，量纲完全相反。如果要加权求和，需要先做归一化，但两种分数的分布不同，归一化后的权重很难调。

RRF（Reciprocal Rank Fusion）只看排名不看原始分数，公式是 `score = 1/(k + rank)`，k 一般取 60。排名越靠前分母越小，分数越高。两路检索结果按 chunk_id 去重融合，同时出现在两路的 chunk 分数叠加，排名更高。

RRF 的优点：不需要归一化，不需要调权重，对分数分布不敏感。
RRF 的缺点：只看排名不看分数差距，如果第一名和第二名距离差很多，RRF 会把它们当成排名差 1 来处理。

---

## 15. BackgroundTasks 重启后会怎样？

BackgroundTasks 是内存级的，进程重启就丢了。代码里先写数据库（status="processing"），再加 BackgroundTasks。所以重启后：文件在磁盘上，数据库记录在，但没人会去解析，文档永远停在 "processing" 状态。

解决方案：启动时扫描数据库里 status="processing" 的文档，重新提交解析任务。

更可靠的方案：用 Celery + Redis 这种持久化任务队列，任务不会因为进程重启丢失。

---

## 16. 为什么 EmbeddingProvider 统一了文档向量化和查询向量化？

embedding 模型把文本映射到一个固定的向量空间。在这个空间里，语义相近的文本距离近，不相关的距离远。但前提是——所有参与计算距离的向量必须来自同一个模型。

如果文档用模型 A 向量化，查询用模型 B 向量化，两个模型的向量空间完全不同，算出来的余弦相似度没有语义含义。即使维度碰巧一样，"Redis" 在两个空间里的坐标也完全不同。

所以把文档向量化和查询向量化封装在同一个 provider 里，确保入库和检索始终用同一个模型、同一个向量空间。同时这个封装也让 reindex、eval 等场景能直接复用。

---

## 17. SSE 流式输出时客户端断开怎么办？

现在的实现：save_chat_turn 放在 generator 末尾，客户端断开 → generator 被垃圾回收 → save_chat_turn 永远不会执行 → 对话丢失。

修复思路：
1. 把写历史的操作从 generator 里拆出来，用 FastAPI 的 response hook 或 middleware，在响应结束时（无论正常还是异常）统一写入
2. 每收到一个 token 就追加到临时存储（比如 Redis），响应结束后再落库。如果中途断开，临时存储里已经有部分内容，可以标记为"未完成"保留下来

---

## 18. negative case 的作用是什么？如果 negative 全对但正常问题引用准确率只有 60%？

negative case 测试的是系统会不会无脑返回引用。如果 negative 全部正确拒答，说明距离阈值能挡住完全无关的查询。

但如果正常问题引用准确率只有 60%，说明问题出在文档之间的混淆——语义相近但不同文档的 chunk 被错误检索。这是两种不同的检索失败模式：negative 失败是"不该检索的检索了"，引用准确率低是"该检索的但检索错了"。

下一步：降 top_k、加同文档加分、或在 chunk metadata 里标记 document_id 做后过滤。

---

## 19. history_service 为什么自己创建 SessionLocal？有什么问题？

Depends(get_db) 只在 FastAPI 路由函数里生效，history_service 是普通函数，不是 FastAPI 调用的，所以不能用依赖注入。

但问题是：路由的 db 和 history_service 的 db 是两个不同的 session，在不同的事务里。如果路由的事务提交了但 history_service 的事务失败回滚，对话历史丢了但文档状态已经改了，数据就不一致。

正确做法：让 history_service 接受外部传入的 db session，整个请求链路共享同一个 session、同一个事务。

---

## 20. eval 的关键词匹配有什么问题？

现在的 contains_keyword 是纯子串匹配：`keyword.lower() in answer.lower()`。

问题："IO多路复用" 和 "I/O 多路复用" 匹配不上，"RDB" 和 "R.D.B" 匹配不上，"setnx" 和 "SET NX" 匹配不上。

但这个问题的影响是单向的——只会低估不会高估，所以评估结果仍然是保守可信的。改进方向是先做分词再匹配，或者对关键词做 normalize（去掉标点、统一大小写）后再比。

---

## 21. Embedding 模型换了怎么办？

如果换了 embedding 模型，所有已入库的向量都需要重新生成，因为不同模型的向量空间不同（参考第 16 题）。

流程：调用 reindex 接口，对每个文档执行 delete_vectors_by_document_id → vectorize_chunks。chunk 内容不变，只重新生成向量。

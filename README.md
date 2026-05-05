# PaiSmart-mini

PaiSmart-mini 是一个基于 FastAPI 的企业知识库 RAG 问答系统。项目围绕两条核心链路实现：文档上传入库链路和流式对话问答链路。

当前版本已经实现文档上传、文本解析、文本切分、Embedding、Chroma 向量库、BM25 + 向量混合检索、SSE 流式问答、多会话历史、引用溯源和 RAG 自动评估。

## 核心功能

- 文档上传：支持文件类型校验、MD5 去重、原始文件保存、后台解析。
- 文档解析：支持 TXT 和 PDF，PDF 使用 PyMuPDF 按页解析，并保留页码。
- 文本清洗：修复 PDF 抽取时常见的英文字符拆散问题，例如 `R e d i s -> Redis`。
- 文本切分：基于 `RecursiveCharacterTextSplitter` 做递归切分，支持 chunk overlap。
- 向量化：统一封装 `EmbeddingProvider`，保证文档入库和查询使用同一套 embedding 模型。
- 向量存储：使用 Chroma 保存 chunk 内容、metadata 和 embedding。
- 混合检索：支持 Chroma 向量检索 + BM25 关键词检索，并使用 RRF 做排名融合。
- 流式问答：基于 FastAPI `StreamingResponse` 和 SSE 实现 token 级流式输出。
- 会话历史：使用数据库保存会话和消息，支持用户多会话管理。
- 引用溯源：回答返回 references，包含文档名、页码和 chunk 片段。
- RAG 评估：支持评估文档命中率、关键词覆盖率、引用准确率、MRR 和分组指标。

## 技术栈

- 后端：FastAPI、SQLAlchemy、Pydantic Settings
- RAG：LangChain、Chroma、BM25、jieba
- 模型：DeepSeek 兼容 OpenAI Chat API、SiliconFlow Embedding API
- 文档解析：PyMuPDF，已实验 Docling
- 前端：原生 HTML/CSS/JavaScript、SSE 流式接收
- 数据库：MySQL 或兼容 SQLAlchemy 的关系型数据库

## 系统架构

```mermaid
flowchart TD
    A["前端页面"] --> B["FastAPI API 层"]
    B --> C["Document Service"]
    B --> D["RAG Service"]
    B --> E["Conversation Service"]

    C --> F["Parser Service"]
    F --> G["Splitter Service"]
    G --> H["document_chunks 表"]
    G --> I["Embedding Service"]
    I --> J["Vector Service"]
    J --> K["Chroma"]

    D --> L["History Service"]
    D --> M["Search Service"]
    M --> N["BM25 Service"]
    M --> K
    D --> O["Chat Model"]

    E --> P["conversation_sessions 表"]
    E --> Q["conversation_messages 表"]
```

## 文档上传入库链路

```mermaid
flowchart TD
    A["用户上传文件"] --> B["校验文件类型"]
    B --> C["分块读取文件流并计算 MD5"]
    C --> D["判断是否重复上传"]
    D --> E["保存原始文件"]
    E --> F["documents 表创建记录 status=processing"]
    F --> G["BackgroundTasks 后台解析"]
    G --> H["parser_service 解析文本"]
    H --> I["clean_text 文本清洗"]
    I --> J["splitter_service 切分 chunks"]
    J --> K["document_chunks 表保存 chunk 原文和页码"]
    K --> L["embedding_service 生成向量"]
    L --> M["vector_service 写入 Chroma"]
    M --> N["回写 vector_id"]
    N --> O["documents 状态改 completed"]
```

如果解析、切分或向量化失败，后台任务会回滚当前数据库事务，并把文档状态更新为 `failed`，同时写入 `error_message`，方便前端展示和排查。

## 流式对话问答链路

```mermaid
flowchart TD
    A["用户发送问题"] --> B["/api/chat/stream"]
    B --> C["rag_service.stream_answer"]
    C --> D["history_service 读取历史消息"]
    C --> E["search_service.hybrid_search"]
    E --> F["向量检索 Chroma"]
    E --> G["BM25 关键词检索"]
    F --> H["RRF 融合排序"]
    G --> H
    H --> I["_format_context 生成参考资料"]
    D --> J["prompt_template"]
    I --> J
    A --> J
    J --> K["chat_model.stream"]
    K --> L["SSE type=chunk 返回前端"]
    K --> M["累计 full_answer"]
    M --> N["save_chat_turn 保存问答和 references"]
    N --> O["SSE type=done"]
```

## 目录结构

```text
app/
  api/                  HTTP 接口层
  models/               SQLAlchemy ORM 模型
  schemas/              请求/响应结构
  services/             核心业务逻辑
  eval/                 RAG 评估脚本和测试用例
  storage/uploads/      原始上传文件
  chroma_data/          Chroma 持久化目录
  main.py               FastAPI 入口
  config.py             配置项
  database.py           数据库连接
```

核心 service 职责：

- `document_service.py`：文档上传、删除、重建、重新向量化。
- `parser_service.py`：文档解析和文本清洗。
- `splitter_service.py`：文本切分和 chunk 保存。
- `embedding_service.py`：文本向量化。
- `vector_service.py`：Chroma 写入、删除和重建。
- `bm25_service.py`：BM25 关键词检索。
- `search_service.py`：向量检索和混合检索。
- `rag_service.py`：RAG 流式问答主流程。
- `history_service.py`：对话历史读写。
- `conversation_service.py`：会话列表和消息查询。

## 环境配置

在 `E:\fastproject\app\.env` 中配置：

```env
DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/paismart_mini?charset=utf8mb4

OPENAI_API_KEY=your_chat_model_key
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-v4-flash

EMBEDDING_KEY=your_embedding_key
EMBEDDING_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-m3

UPLOAD_DIR=./storage/uploads
CHROMA_PERSIST_DIR=./chroma_data
CHROMA_COLLECTION_NAME=documents
RAG_MAX_DISTANCE=0.95
```

注意：不要把真实 API Key 提交到 Git 仓库。

## 启动后端

```powershell
cd E:\fastproject\app
D:\anaconda\envs\lc\python.exe -X utf8 -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

健康检查：

```text
GET http://127.0.0.1:8000/api/health
```

## 启动前端

```powershell
cd E:\fastproject\rag-frontend
D:\anaconda\envs\lc\python.exe -X utf8 server.py
```

访问：

```text
http://127.0.0.1:5177
```

前端代理会把 `/api/*` 请求转发到 `http://127.0.0.1:8000`，并支持 SSE 流式响应。

## RAG 评估

运行评估：

```powershell
cd E:\fastproject\app
D:\anaconda\envs\lc\python.exe -X utf8 eval\eval_rag.py
```

评估默认不会写入聊天历史。需要保存评估会话时可以使用：

```powershell
D:\anaconda\envs\lc\python.exe -X utf8 eval\eval_rag.py --save-history --keep-db
```

当前评估指标包括：

- 文档命中率
- MRR
- 平均关键词覆盖率
- 引用证据关键词覆盖率
- 引用预期准确率
- 平均引用精确率
- 无关问题拒引率
- 按 case 分组统计

## 当前完成度

已完成：

- 核心 RAG 入库链路
- 流式问答链路
- 数据库多会话历史
- 引用溯源
- BM25 + 向量混合检索
- RAG 自动评估脚本
- 文档清洗和 Docling 解析实验

后续计划：

- Docling 可选解析器接入主流程
- Rerank 重排序
- 知识库隔离和用户权限
- MinIO 文件存储
- 大文件分片上传和断点续传
- Elasticsearch / OpenSearch 检索后端
- Agent 工具调用能力

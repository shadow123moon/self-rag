# API 文档

服务地址：

```text
http://127.0.0.1:8000
```

通用响应格式：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

部分接口当前只返回 `code` 和 `data`，这是项目当前实现状态。

## 健康检查

### GET /api/health

检查后端服务是否正常。

响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "status": "ok"
  }
}
```

## 文档接口

### POST /api/documents/upload

上传文档。后端会校验文件类型、计算 MD5、保存原始文件、创建文档记录，并通过后台任务执行解析、切分和向量化。

请求类型：`multipart/form-data`

参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| file | UploadFile | 是 | 上传的文档文件 |

响应示例：

```json
{
  "code": 0,
  "data": {
    "document_id": "a3ed8e8d597c4291b4a190d6631155ee",
    "filename": "面渣逆袭 Redis 篇.pdf",
    "status": "processing"
  }
}
```

### GET /api/documents/

获取文档列表。

响应示例：

```json
{
  "code": 0,
  "data": [
    {
      "document_id": "a3ed8e8d597c4291b4a190d6631155ee",
      "filename": "面渣逆袭 Redis 篇.pdf",
      "file_type": ".pdf",
      "status": "completed",
      "chunk_count": 82,
      "created_at": "2026-05-03T12:00:00"
    }
  ]
}
```

### GET /api/documents/{document_id}

获取单个文档详情。

路径参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| document_id | string | 文档 ID |

响应示例：

```json
{
  "code": 0,
  "data": {
    "document_id": "a3ed8e8d597c4291b4a190d6631155ee",
    "filename": "面渣逆袭 Redis 篇.pdf",
    "file_type": ".pdf",
    "file_path": "./storage/uploads/xxx.pdf",
    "file_md5": "d41d8cd98f00b204e9800998ecf8427e",
    "file_size": 102400,
    "status": "completed",
    "chunk_count": 82,
    "error_message": null,
    "created_at": "2026-05-03T12:00:00",
    "updated_at": "2026-05-03T12:01:00"
  }
}
```

### GET /api/documents/{document_id}/chunks

获取某个文档的所有 chunk。

响应示例：

```json
{
  "code": 0,
  "data": [
    {
      "chunk_id": "3c0980b0dc734741b37ce877b94b1912",
      "chunk_index": 0,
      "content": "Redis 是一种基于键值对的 NoSQL 数据库...",
      "page_number": 1,
      "vector_id": "3c0980b0dc734741b37ce877b94b1912"
    }
  ]
}
```

### DELETE /api/documents/{document_id}

删除文档。删除时会清理 Chroma 向量、数据库 chunk、文档记录和原始文件。

响应示例：

```json
{
  "code": 0,
  "message": "文档已删除",
  "data": {
    "document_id": "a3ed8e8d597c4291b4a190d6631155ee",
    "deleted_chunks": 82,
    "deleted_vectors": 82
  }
}
```

### POST /api/documents/{document_id}/rebuild

完整重建文档。适用于解析逻辑、清洗逻辑或切分逻辑发生变化的场景。

流程：

```text
删除旧向量
删除旧 chunks
重新解析原始文件
重新清洗文本
重新切分
重新向量化
写入 Chroma
```

响应示例：

```json
{
  "code": 0,
  "message": "文档开始重建",
  "data": {
    "document_id": "a3ed8e8d597c4291b4a190d6631155ee",
    "status": "processing"
  }
}
```

### POST /api/documents/{document_id}/reindex

重新向量化文档。适用于 chunk 内容不变，但向量丢失或 embedding 模型变更的场景。

注意：如果修改了 parser 或 splitter，需要使用 `rebuild`，不是 `reindex`。

响应示例：

```json
{
  "code": 0,
  "message": "文档重新向量化成功",
  "data": {
    "document_id": "a3ed8e8d597c4291b4a190d6631155ee",
    "chunk_count": 82
  }
}
```

## 检索接口

### POST /api/search/

执行向量检索，返回 Chroma 相似结果和分数。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| query | string | 无 | 查询文本 |
| top_k | int | 3 | 返回数量 |

请求示例：

```text
POST /api/search/?query=Redis为什么这么快&top_k=5
```

响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "query": "Redis为什么这么快",
    "results": [
      {
        "chunk_id": "3c0980b0dc734741b37ce877b94b1912",
        "document_id": "a3ed8e8d597c4291b4a190d6631155ee",
        "score": 0.7038,
        "content": "Redis 是一种基于内存的数据库...",
        "metadata": {
          "source": "document",
          "page": 1
        }
      }
    ]
  }
}
```

## 流式对话接口

### POST /api/chat/stream

基于 RAG 的流式问答接口。后端使用 SSE 返回流式事件。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| message | string | 无 | 用户问题 |
| user_id | string | default_user | 用户 ID |
| session_id | string | default | 会话 ID |
| top_k | int | 5 | 检索数量 |

请求示例：

```text
POST /api/chat/stream?message=Redis为什么这么快&user_id=user_1&session_id=session_1&top_k=5
```

响应类型：

```text
Content-Type: text/event-stream
```

事件示例：

```text
data: {"type":"chunk","content":"Redis"}

data: {"type":"chunk","content":" 速度快主要因为..."}

data: {"type":"done","answer":"Redis 速度快主要因为...","user_id":"user_1","session_id":"session_1","references":[...]}
```

`chunk` 事件表示模型正在生成的片段。  
`done` 事件表示本轮回答结束，并返回完整答案和引用来源。

## 会话接口

### GET /api/conversations/

获取某个用户的会话列表。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| user_id | string | default_user | 用户 ID |

响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": [
    {
      "session_id": "f8dbb44422204dc48a27560f10c4baac",
      "db_session_id": "user_1__f8dbb44422204dc48a27560f10c4baac",
      "user_id": "user_1",
      "title": "Redis为什么这么快？",
      "status": "active",
      "message_count": 4,
      "last_message": "Redis 速度快主要因为...",
      "updated_at": "2026-05-03T12:00:00",
      "created_at": "2026-05-03T11:59:00"
    }
  ]
}
```

### POST /api/conversations/

创建新会话。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| user_id | string | default_user | 用户 ID |
| title | string | 新对话 | 会话标题 |

响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "session_id": "f8dbb44422204dc48a27560f10c4baac",
    "user_id": "user_1",
    "title": "新对话",
    "status": "active"
  }
}
```

### GET /api/conversations/{session_id}/messages

获取某个会话的消息列表。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| user_id | string | default_user | 用户 ID |

响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "session": {
      "session_id": "f8dbb44422204dc48a27560f10c4baac",
      "title": "Redis为什么这么快？"
    },
    "messages": [
      {
        "message_id": "msg_1",
        "session_id": "f8dbb44422204dc48a27560f10c4baac",
        "user_id": "user_1",
        "role": "user",
        "content": "Redis为什么这么快？",
        "references": null,
        "created_at": "2026-05-03T12:00:00"
      },
      {
        "message_id": "msg_2",
        "role": "assistant",
        "content": "Redis 速度快主要因为...",
        "references": [
          {
            "index": 1,
            "document_id": "a3ed8e8d597c4291b4a190d6631155ee",
            "filename": "面渣逆袭 Redis 篇.pdf",
            "page": 8,
            "content": "Redis 使用 IO 多路复用..."
          }
        ],
        "created_at": "2026-05-03T12:00:05"
      }
    ]
  }
}
```

### DELETE /api/conversations/{session_id}

删除某个会话。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| user_id | string | default_user | 用户 ID |

响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "session_id": "f8dbb44422204dc48a27560f10c4baac",
    "message": "对话已删除"
  }
}
```

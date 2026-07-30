# API Design

Base URL：`http://127.0.0.1:8000`

除 SSE 外，响应均为 JSON。应用会在响应中返回 `X-Request-ID`；客户端也可传入不超过 128 字符的 `X-Request-ID`，该值同时用于会话 exchange 的 `turn_id` 幂等键。

如果 `APP_API_KEY` 非空，除 `/`、`/health` 和 `/health/ready` 外的端点都需要：

```http
X-API-Key: <APP_API_KEY>
```

## 1. Health

### `GET /`

进程信息：

```json
{"message": "Local RAG System 正在运行"}
```

### `GET /health`

只检查应用进程，不访问外部依赖：

```json
{"status": "ok"}
```

### `GET /health/ready`

检查 Qdrant、配置的 LLM endpoint 和 embedding endpoint。

全部可达时返回 200：

```json
{
  "status": "ready",
  "dependencies": {
    "qdrant": {"status": "ok"},
    "llm": {"status": "ok"},
    "embedding": {"status": "ok"}
  }
}
```

任一不可达时返回 503。客户端只会看到异常类型，不会看到内部 URL、路径或凭据：

```json
{
  "status": "not_ready",
  "dependencies": {
    "qdrant": {"status": "unavailable", "error": "ResponseHandlingException"},
    "llm": {"status": "ok"},
    "embedding": {"status": "ok"}
  }
}
```

## 2. Documents

支持 `.pdf`、`.txt`、`.md`、`.markdown`、`.docx`。默认单文件硬上限由 `UPLOAD_MAX_BYTES` 控制，默认 25 MiB。

### `POST /documents/upload`

`multipart/form-data`：

```text
file=<binary>
```

成功 200：

```json
{
  "status": "indexed",
  "filename": "guide.md",
  "source": "guide.md",
  "document_id": "0de2d27e-...",
  "chunks": 12,
  "change_type": "new",
  "cleanup_pending": false
}
```

同名同内容再次上传会返回 `status=up_to_date`、`change_type=unchanged`，并清理本次新建的临时 UUID 文件。同名但内容变化被视为稳定文档的新版本。响应不会暴露服务端 UUID 存储路径。

`cleanup_pending=true` 表示新版本已经激活，但旧版本清理失败并留在 SQLite 持久化队列等待下次幂等重试；此时不会回滚已经激活的新版本。

错误：

| 状态码 | 场景 |
|---:|---|
| 400 | 扩展名不支持、PDF/DOCX/UTF-8 内容校验失败 |
| 413 | 超过上传字节上限 |
| 500 | 保存或摄取内部失败；临时文件会尝试清理 |

### `POST /documents/upload-batch`

同一个 `files` 字段传多个文件。文件顺序处理，一个失败不阻止后续文件：

```json
{
  "results": [
    {
      "status": "indexed",
      "document_id": "0de2d27e-...",
      "source": "guide.md",
      "chunks": 12
    },
    {
      "filename": "fake.pdf",
      "status": "error",
      "error": "Invalid PDF content"
    }
  ]
}
```

批量端点用逐文件 `status` 表示部分失败，因此有效 multipart 请求通常返回 200。

### `GET /documents`

```json
[
  {
    "document_id": "0de2d27e-...",
    "source": "guide.md",
    "file_type": ".md",
    "chunks": 12
  }
]
```

旧索引没有稳定 ID 时，`document_id` 可能为 `null`。

### `DELETE /documents/{identifier}`

新客户端应传 `document_id`。为兼容旧客户端，也可以传 source，但只有唯一匹配时才删除。

成功 200：

```json
{
  "document_id": "0de2d27e-...",
  "source": "guide.md",
  "deleted_chunks": 12,
  "file_deleted": true,
  "state_deleted": true,
  "status": "deleted"
}
```

错误：

| 状态码 | 场景 |
|---:|---|
| 404 | 没有对应文档 |
| 409 | 同一个 source 对应多个候选，必须改用 `document_id` |
| 500 | Qdrant、注册表或文件操作异常 |

409 响应只给出候选的 ID/source，不暴露内部存储路径；客户端不应自动任选一个。

## 3. RAG

### 请求模型

```json
{
  "question": "How does the ingestion pipeline avoid data loss?",
  "conversation_id": "conversation-1",
  "history": [
    {"role": "user", "content": "Tell me about ingestion."},
    {"role": "assistant", "content": "It is versioned."}
  ],
  "force_rag": false
}
```

约束：

| 字段 | 约束 |
|---|---|
| `question` | 必填，1–20000 字符 |
| `conversation_id` | 可空；1–64 位 `[A-Za-z0-9_-]` |
| `history` | 最多 100 条 |
| `history[].role` | `user` 或 `assistant` |
| `history[].content` | 最大 100000 字符 |
| `force_rag` | 默认 `false` |

`history` 不是服务端长期记忆的替代品，只用于与可能尚未落库的浏览器尾部对账。

### `POST /rag/query`

成功 200：

```json
{
  "question": "How does the ingestion pipeline avoid data loss?",
  "answer": "It writes a new version before deleting the old one...",
  "sources": [
    {
      "content": "...",
      "source": "architecture.md",
      "file_name": "architecture.md",
      "file_path": "docs/architecture.md",
      "chunk_index": 3,
      "page": null,
      "score": 0.83
    }
  ],
  "conversation_id": "conversation-1",
  "routing": "rag"
}
```

`routing`：

| 值 | 行为 |
|---|---|
| `greeting` | Layer 0 固定快速回复，无检索 |
| `direct` | Layer 1 直接回答，无检索 |
| `rag` | 检索并基于文档生成；`force_rag` 也会进入该路径 |

`sources[].score` 是当前 vector/Rerank 策略的排序分数，不保证跨策略同量纲。客户端只应在相同策略与配置内比较，不应使用一个固定阈值解释所有分数。

错误：

| 状态码 | 场景 |
|---:|---|
| 413 | 当前问题无法装入配置的上下文窗口 |
| 422 | 请求模型校验失败 |
| 500 | 查询链路失败；响应不暴露内部异常 |

### `POST /rag/query/stream`

响应类型：`text/event-stream`。

每个事件都使用 JSON 编码的 `data`，包括 token 字符串：

```text
event: routing
data: {"routing":"rag","conversation_id":"conversation-1"}

event: status
data: {"phase":"searching","message":"Searching documents..."}

event: token
data: "It writes"

event: sources
data: [{"content":"...","source":"architecture.md","score":0.83}]

event: done
data: {}
```

状态 phase 可能为 `searching`、`reranking`、`generating` 或 direct path 的 `responding`。

流中错误：

```text
event: error
data: {
  "message": "Unable to retrieve relevant documents.",
  "phase": "retrieval",
  "conversation_id": "conversation-1"
}

event: done
data: {}
```

错误 phase：

- `context`
- `routing`
- `retrieval`
- `rerank`
- `generation`

失败路径不会再发送正常 `sources`，也不会把已经输出的部分 token 保存为完整回答。客户端断开触发取消时同样不保存。

## 4. Conversations

### `GET /conversations`

按最近更新时间倒序：

```json
[
  {
    "id": "conversation-1",
    "title": "How does ingestion work?",
    "created_at": 1785450000.0,
    "updated_at": 1785450010.0,
    "message_count": 2
  }
]
```

### `GET /conversations/{id}`

返回会话元数据和全部原始消息。assistant 消息可包含 `sources` 与 `routing`。

不存在返回 404。

### `DELETE /conversations/{id}`

成功：

```json
{"ok": true, "deleted": "conversation-1"}
```

不存在返回 404。

## 5. 错误与安全约定

- 422 由 Pydantic/FastAPI 请求验证生成。
- 可操作的用户输入错误使用 400/409/413。
- 未预期异常向客户端返回稳定、泛化文本，细节写服务端日志。
- readiness 公开，便于 Docker/Kubernetes 探测；业务接口可由可选 API Key 保护。
- SSE 一旦发出响应头，后续错误必须通过 event 表达。
- `X-Request-ID` 用于关联服务端日志、阶段耗时和幂等会话写入。

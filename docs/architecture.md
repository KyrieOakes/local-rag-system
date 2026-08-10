# Architecture

本文描述当前代码，而不是早期 DevLog 中已经被替换的实现。

## 1. 分层

```text
app/api/       HTTP、multipart、SSE、状态码
      ↓
app/services/  用例编排与跨模块事务边界
      ↓
app/rag/       检索、上下文、生成、摄取等领域原语
      ↓
Qdrant / SQLite / OpenAI-compatible endpoints / filesystem
```

- API 层不实现检索算法，只负责协议转换和错误映射。
- Service 层决定调用顺序，例如“先恢复记忆，再路由，再检索，再生成”。
- RAG 层中的组件尽量可单测：token 预算、evidence 匹配、reranker 和版本 ID 都可脱离真实服务验证。
- Qdrant 保存 dense/BM25 表示与 chunk payload；SQLite 分别保存文档注册状态和会话状态。

## 2. 摄取链路

```mermaid
sequenceDiagram
    participant C as CLI / Upload API
    participant P as ingest_pipeline
    participant S as ChecksumStore
    participant E as Embedding API
    participant Q as Qdrant

    C->>P: file path + source + collection
    P->>S: lookup(document_id, collection)
    P->>P: MD5 + pipeline fingerprint + version_id
    alt 内容和管线都未变化
        P-->>C: up_to_date
    else 新增或变化
        P->>P: load + split + per-file chunk_index
        P->>E: bounded concurrent embedding batches
        P->>Q: validate schema + upsert new version (wait=true)
        alt upsert 失败
            P->>Q: compensate delete new version
            P-->>C: error，旧注册状态不变
        else upsert 成功
            P->>S: atomic activate new + enqueue old cleanup
            alt SQLite 激活失败
                P->>Q: compensate delete new version
                P-->>C: error，旧版本仍有效
            else 激活成功
                P->>Q: idempotent cleanup predecessor
                alt cleanup 失败
                    P-->>C: indexed + cleanup_pending
                else cleanup 成功
                    P->>S: complete cleanup record
                    P-->>C: indexed
                end
            end
        end
    end
```

### 文档身份

- 目录文件：identity key 来自规范化绝对路径。
- 单文件上传：identity key 来自 Unicode NFC 规范化后的原始文件名。
- 文件夹上传：identity key 来自浏览器提供并经服务端校验的 NFC 相对路径；因此 `backend/README.md` 与 `frontend/README.md` 是两个独立逻辑文档。
- `document_id` 还包含 collection，因此同一文件在不同 collection 中互不影响。
- 单文件同名或文件夹同相对路径被视为同一逻辑文档的新版本；内容也相同则删除新临时 UUID 文件并返回 `up_to_date`。
- Qdrant point ID 由 `document_id + version_id + chunk_index` 确定，重复执行同一版本是幂等 upsert。

### 管线指纹

指纹包含：

- collection；
- embedding base URL、model、人工维护的 revision；
- chunk size、overlap；
- splitter version；
- 索引 schema；Hybrid schema 下还包含 BM25 model/tokenizer/language 和 dense/sparse 向量名。

它解决“文件 MD5 没变，但向量或切分语义已经变了”的漏更新问题。

### 一致性边界

Qdrant 和 SQLite 不共享事务。当前使用“新版本先同步写入 + SQLite 原子激活/清理任务 + 幂等清旧”的本地 saga：

- loader、splitter、embedding 失败：不触碰旧向量；
- 新 Qdrant 写入失败：按新 version 精确回滚；
- SQLite 激活事务失败：回滚新 Qdrant version，旧注册状态不变；
- 激活成功后才清理旧版本；失败时新版保持有效，durable cleanup queue 等待下次重试；
- 旧 UUID 上传按 Qdrant 的原 source/path 归并到新原始文件名身份；
- 目录删除只清理注册在同一个 scan root 且路径仍位于该 root 内的记录。

这比先删旧版本可靠，但仍不是跨存储 ACID。生产多节点场景应把本地清理队列迁移到共享 outbox/任务系统，并增加租约、可重试状态机和一致性巡检。

### 摄取并发边界

一个浏览器 multipart 批次最多由 `UPLOAD_INGESTION_CONCURRENCY` 个 document worker 并行执行加载、切分、embedding 和 upsert。所有 document worker 共用由 `EMBEDDING_MAX_CONCURRENCY` 限制的进程级 embedding 请求池，因此文件数增加不会无限创建到 LM Studio 的并发请求。每个请求最多携带 `EMBEDDING_BATCH_SIZE` 个 chunk，异步完成后按 batch index 和 endpoint 返回的 chunk index 恢复原始顺序。

外层 ingestion lock 仍覆盖一个显式批次，防止其他摄取操作穿插版本生命周期；批次内部只并行彼此独立的文件。Qdrant collection 的首次 create/schema validate 另有短临界区，避免两个首批文件同时创建 collection。

## 3. 查询链路

```mermaid
flowchart TD
    A["QueryRequest"] --> B["恢复 SQLite 摘要与近期消息"]
    B --> C["与客户端尾部最长重叠对账"]
    C --> D["路由上下文预算"]
    D --> E{"Layer 0 命中?"}
    E -- 是 --> F["固定 quick reply"]
    E -- 否 --> G["Layer 1 JSON 路由/意图/改写"]
    G --> H{"needs_rag 或 force_rag?"}
    H -- 否 --> I["direct answer"]
    H -- 是 --> J{"Retrieval mode"}
    J -- dense --> JD["Dense recall"]
    J -- bm25 --> JB["BM25 recall"]
    J -- hybrid --> JH["Dense + BM25 prefetch → RRF/DBSF"]
    JD --> K{"Rerank enabled?"}
    JB --> K
    JH --> K
    K -- Cross-Encoder / Hybrid --> L["candidate N → final K"]
    K -- none --> M["保留 TOP_K"]
    L --> N["统一生成上下文预算"]
    M --> N
    N --> O["LCEL prompt → LLM → parser"]
    F --> P["完整回答完成"]
    I --> P
    O --> P
    P --> Q["同步事务：exchange + memory job"]
    Q --> R["completed/warning + done"]
    Q --> W["空闲时 Memory Worker 摘要"]
    P --> T["有界后台 JSONL trace"]
```

Layer 1 要求 JSON 输出，并兼容旧的行协议。解析失败、模型异常或缺少 direct answer 时不会贸然跳过知识库，而是使用原始问题继续 RAG。

### Hybrid collection 与召回

为避免原地迁移产生“部分 point 只有 dense、部分 point 同时有 sparse”的混合状态，旧 collection 默认保持 unnamed dense schema；启用 Hybrid 时使用新 collection，并设置 `RETRIEVAL_INDEX_SCHEMA=hybrid`。每个新 point 同时写入 named dense vector 与启用 IDF 的 BM25 sparse vector，二者与 payload 共用同一个确定性 point ID，因此原有版本回滚和精确删除会一起处理两种表示。

`RETRIEVAL_MODE` 可在 Hybrid collection 上选择 dense-only、bm25-only 或 hybrid。Hybrid 查询由 Qdrant 对两路 prefetch 执行 RRF（默认）或 DBSF，再把融合候选交给可选 Cross-Encoder。摄取与查询通过 `app/rag/bm25.py` 共用 multilingual tokenizer 和 language 配置。

### Rerank score 契约

召回结果先转换为：

```python
RerankCandidate(document=..., retrieval_score=...)
```

这样 Cross-Encoder 和旧轻量关键词融合不依赖易丢失的 metadata 隐式分数；`retrieval_score` 可以是 dense、BM25 或 RRF/DBSF 得分。`vector_score` 只保留为兼容 metadata。Cross-Encoder 返回模型分数；失败 fallback 回到一阶段检索分数。旧 `HybridFusionReranker` 是关键词覆盖精排，不应与 BM25 Hybrid 召回混为一谈。

## 4. 上下文与长期记忆

模型侧记忆：

```text
structured rolling summary + pending-compaction complete turns
+ complete recent turns + reconciled client tail
```

UI 侧历史：

```text
all original messages
```

服务端优先使用持久化 `turn_id` 把 user/assistant 消息组成完整问答轮次，旧记录和浏览器尾部回退到相邻角色配对。最近窗口同时满足 `CONTEXT_SHORT_TERM_MAX_TURNS=6` 与 `CONTEXT_SHORT_TERM_MAX_TOKENS=4096`；更早但尚未进入摘要的完整轮次进入独立的 `CONTEXT_PENDING_MEMORY_MAX_TOKENS=2048` 缓冲区，避免后台压缩完成前出现上下文断层。最新一轮即使超长，也会作为完整角色对一起截断，不会只向模型注入半轮。

可压缩旧轮次达到 `CONTEXT_SUMMARY_BATCH_TURNS=4` 或 `CONTEXT_SUMMARY_TRIGGER_TOKENS=2048` 时，后台 LLM 把旧摘要和这些完整轮次合并为 schema v1 JSON：`summary`、`goals`、`constraints`、`decisions`、`entities`、`open_questions`。只有 JSON 结构和 token 上限都校验成功才推进 `summary_through_message_id`；失败时待压缩缓冲和近期原文仍可用。SQLite 同时保存 `summary_schema_version`、递增的 `summary_revision` 和 `summary_token_count`。

完整 answer 保存时，user/assistant exchange 与一条按 conversation 合并的 `conversation_memory_jobs` 记录在同一事务中提交。单线程 Memory Worker 使用 `pending/running/retry/dead` 状态、租约和指数退避领取任务；进程重启会补齐没有 job 的未摘要会话。Worker 只在没有活跃用户查询时启动新的摘要调用，避免后台任务主动与交互链路争用本地模型。摘要调用一旦开始不能被同步 provider 抢占，这是当前单进程边界。

摘要只推进游标，不删除原始消息。这样可以展示完整历史、审计摘要、改变策略后重新生成。读取旧数据库时，如果历史游标恰好停在 user 消息后，Store 会临时补回这个边界消息，让下一次结构化压缩恢复完整 turn。

### 预算

路由和生成分别计算输入上限。生成阶段：

```text
input_limit
= llm_context_window
- reserved_output_tokens
- safety_margin_tokens
```

固定占用包含 system prompt、当前问题和消息协议估算。剩余预算在摘要、待压缩原文、近期原文和按相关性排序的文档之间分配。最终还会渲染完整 prompt 再检查一次，避免各部分独立计数的边界误差。

### 超限策略

1. 不截断当前问题；
2. 先从最新完整 turn 向前保留，再用独立上限保留最新的待压缩 turn；
3. 最新 turn 过长时同时保留并截断 user/assistant 两条消息；
4. 文档按排名装入，最后一块可截断；
5. 仍无法容纳则抛出 `ContextWindowExceededError`。

同步接口映射为 413；SSE 因响应已开始，使用 error event。

## 5. SSE 与异步边界

`query_rag_stream()` 是 async generator，但 SQLite 恢复、路由模型、Qdrant 检索、Rerank 和上下文规划中可能包含同步阻塞工作。这些阶段通过 `asyncio.to_thread` 移出事件循环。

事件序列：

```text
正常: memory status → routing status → routing
    → retrieval status → [rerank status] → context status
    → generation status → token* → finalizing running
    → sources → finalizing completed|warning → done
失败: [routing] → [status*] → error → done
取消: 重新抛出 CancelledError，不落库
```

每个耗时阶段在真正执行前发送 `state=running`，成功后发送 `state=completed` 和实测 `elapsed_ms`。检索完成事件包含候选数，Rerank 包含输入/输出数量，上下文完成事件包含纳入 chunk 数、pending/recent turn 数和 input token 数。前端据此显示实时步骤时间线；完成后折叠时间线，并把重复 chunk source 合并为文档级标签，不在回答区直接展示不同量纲的检索分数。

direct answer 使用固定字符切片，而不是 `split()`，因此中文、换行和连续空格不会被破坏。

生成结束后才执行完成态副作用：

- 同步 finalization 保存 user/assistant 完整 exchange，并在同一事务 upsert memory job；
- 使用 request ID 作为 `turn_id`；同一请求或重试复用该 ID 时，通过唯一索引避免重复写；
- Memory Worker 在请求路径之外按阈值压缩长期记忆；
- 有界后台执行器将 query、routing、retrieval、answer 和阶段耗时写入 JSONL。

会话保存失败不会抹掉已生成答案：SSE 发送 `finalizing warning` 和 `done.conversation_persisted=false`，前端保留回答并展开黄色警告。查询轨迹执行器有固定 worker 和有界队列；容量耗尽时拒绝任务并记录错误，而不是无限创建线程或无限堆积内存。应用关闭时 drain 已接收 trace，并停止 Memory Worker。

## 6. 数据存储

### `data/ingestion_state.db`

`document_registry` 是权威表，主要字段：

```text
document_id, collection_name, identity_key, source, stored_path,
content_md5, pipeline_fingerprint, version_id, chunk_count,
origin, scan_root, last_ingested_at
```

旧 `file_checksums` 表保留为兼容镜像，启动时可迁移旧数据。

### `data/conversations.db`

```text
conversations:
  id, title, summary, summary_through_message_id,
  summary_schema_version, summary_revision, summary_token_count,
  created_at, updated_at

messages:
  id, conversation_id, role, content, sources, routing, turn_id, created_at

conversation_memory_jobs:
  conversation_id, requested_through_message_id, status, attempts,
  available_at, lease_owner, lease_until, last_error_code, timestamps
```

SQLite 使用 WAL、busy timeout、外键和同会话条带锁。消息读取按自增 ID 排序，exchange 与 memory job 使用同一事务；删除 conversation 时 job 通过外键级联删除。

### Qdrant payload

```text
page_content
metadata:
  document_id, version_id, source, stored_path, file_path,
  file_name, file_type, chunk_index, md5, pipeline_fingerprint,
  page / markdown headings ...
```

## 7. 进程内缓存

- Embedding query cache：256 条真正的 LRU，key 包含 base URL、model 和原文的 SHA-256。
- Embedding model client、QdrantVectorStore 和 Qdrant retrieval client 按有效配置复用。
- Cross-Encoder 首次使用时懒加载。
- tokenizer encoding 使用 `lru_cache`。

这些缓存是单进程的，重启即失效，也不会跨多个 worker 共享。

## 8. 安全边界

- 源码和 `.env.example` 不含真实云密钥；
- cloud provider 被选择但 key 为空时，配置启动即失败；
- CORS allowlist 可配置；
- 可选 `X-API-Key` 使用恒定时间比较；
- 上传按流式字节数限制，并检查 PDF magic、DOCX zip 结构、文本 UTF-8；
- 文件夹相对路径拒绝绝对路径、父目录、驱动器前缀、空段以及过深/过长值，且末段必须匹配 multipart 文件名；
- 相对路径只用于 source 和稳定身份；上传文件使用 UUID 存储，删除函数拒绝 `data/raw` 外路径；
- 浏览器目录遍历使用异步 File System Access API 或 WebKit 回退，前端按 20 个文件顺序提交；后端把磁盘写入、内容检查和同步摄取移出事件循环；
- conversation ID 和请求体有长度/字符约束；
- prompt 明确把历史和检索文档视为不可信数据。

剩余风险：API Key 不是用户认证体系，RAG 文档仍可能包含间接 prompt injection，Markdown 链接策略和文件解析器还需要持续安全审查。

## 9. 评估语义

`evidence-label-v2` 把 golden evidence 作为稳定评估单位，而不是把“成功映射到的 chunk”反向当作分母。

- Recall：命中的唯一 evidence / 全部 golden evidence；
- Precision：前 K 个槽位中首次提供新 evidence 的槽位 / K；
- MRR：首个相关槽位倒数；
- NDCG：保留噪声和重复槽位的真实排名；
- context quality：仍从 chunk 角度统计无关和重复。

报告的 provenance 用 dataset hash、Git 状态和 settings fingerprint 防止把不同数据或配置误当作同一实验。旧指标语义报告不会进入 Notebook 的新策略对比。

## 10. 扩展方向

如果从当前单节点项目演进：

1. 文档 catalog 独立于 Qdrant，提供分页和状态机；
2. SQLite 迁移到 PostgreSQL，后台副作用迁移到可靠队列；
3. 扩大 lexical/identifier/中文 golden dataset，在验证集上选择 RRF、DBSF 或权重；
4. 使用模型原生 tokenizer，并评估摘要事实保留；
5. 接入 OpenTelemetry/Prometheus、trace backend 和告警；
6. 增加真实依赖集成、浏览器 E2E、并发压测和故障注入；
7. 再引入用户、租户、RBAC、限流和审计策略。

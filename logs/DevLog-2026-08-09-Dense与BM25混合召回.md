# Dev Log — Dense 与 BM25 混合召回

> **日期**: 2026-08-09  
> **标签**: feature, rag, retrieval, bm25, qdrant, rrf, evaluation

---

## 一、概述

在保留旧 unnamed dense collection 可直接继续使用的前提下，新增 Qdrant 原生 BM25 sparse 召回与 dense + BM25 服务端融合。新 Hybrid collection 的每个 point 同时保存 named dense vector、启用 IDF 的 BM25 sparse vector 和原 chunk payload，以 RRF 为默认融合策略，也支持 DBSF。

本次将“索引能力”与“查询策略”分开：`RETRIEVAL_INDEX_SCHEMA` 决定 collection 是旧 dense schema 还是新 hybrid schema，`RETRIEVAL_MODE` 决定当前查询走 dense、BM25 还是双路融合。默认仍为 `dense/dense`，因此未配置的现有部署不会被强制迁移。

---

## 二、新增/修改的文件清单

### 后端与摄取

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/core/config.py` | **修改** | 新增 index schema、retrieval mode、BM25、向量名、fusion 和 prefetch 配置及跨字段校验 |
| `app/rag/bm25.py` | **新增** | 统一构造摄取与查询使用的 Qdrant BM25 `Document` |
| `app/rag/ingestion/bulk_writer.py` | **修改** | 创建/校验 Hybrid collection，同 point 写入 dense + sparse |
| `app/rag/ingestion/ingest_pipeline.py` | **修改** | 将 index schema 与 BM25 语义纳入 pipeline fingerprint |
| `app/rag/retriever.py` | **修改** | 新增 dense-only、BM25-only、RRF/DBSF Hybrid 查询，保持统一返回契约 |
| `app/rag/vectorstore.py` | **修改** | 暴露可复用的 Qdrant client 工厂 |
| `app/rag/reranker.py` | **修改** | 一阶得分改为 `retrieval_score`，保留 `vector_score` 兼容别名 |
| `app/services/rag_service.py` | **修改** | 日志和语义适配可配置的一阶检索 |
| `app/rag/query_logger.py` | **修改** | trace 记录 schema、mode、fusion 和 prefetch |
| `.env.example` | **修改** | 增加安全的 dense 默认值与 Hybrid 迁移说明 |

### 评估、测试与文档

| 文件 | 操作 | 说明 |
|------|------|------|
| `evaluation/run_retrieval_eval.py` | **修改** | 支持按模式/fusion/prefetch 运行生产 Retriever，记录完整 provenance |
| `evaluation/retrieval_eval_pipeline.ipynb` | **修改** | Notebook 报告补充 Hybrid 配置快照 |
| `tests/test_retriever.py` | **新增** | dense/BM25/RRF/DBSF、schema 拒绝与 payload 校验回归测试 |
| `tests/test_config.py` | **修改** | 增加 Hybrid 配置跨字段校验 |
| `tests/test_ingestion_lifecycle.py` | **修改** | 验证指纹、同 point 双表示与 sparse schema 错误 |
| `tests/test_reranker.py` | **修改** | 验证 `retrieval_score` metadata |
| `tests/test_retrieval_eval_runner.py` | **修改** | 验证评估报告中的 Hybrid provenance |
| `README.md` | **修改** | 补充架构、配置、蓝绿迁移、检索/精排边界和限制 |
| `docs/architecture.md` | **修改** | 更新 Hybrid 数据流、collection schema 和得分契约 |
| `docs/api_design.md` | **修改** | 说明 source score 的策略内可比性 |
| `evaluation/README.md` | **修改** | 增加 dense/BM25/hybrid 对照评估方法 |
| `logs/项目说明与进度.md` | **修改** | 增加 Sprint 9 当前能力与限制 |
| `AGENTS.md` | **修改** | 同步当前架构、迁移规则和测试数 |

---

## 三、接口与配置设计

### 3.1 HTTP 接口

`POST /rag/query` 与 `POST /rag/query/stream` 的请求/响应结构不变。Retriever 继续返回 `list[tuple[Document, float]]`，因此路由、会话记忆、上下文预算、SSE 和来源展示无需分支处理 BM25。

`sources[].score` 表示当前策略的最终排序分数，可能是 dense cosine、BM25、RRF/DBSF 或 Cross-Encoder 分数。不同策略不同量纲，不应使用同一固定阈值跨策略解释。

### 3.2 默认兼容配置

```dotenv
QDRANT_COLLECTION=local_rag_docs
RETRIEVAL_INDEX_SCHEMA=dense
RETRIEVAL_MODE=dense
```

这条路径仍使用旧 unnamed dense vector，不要在原 collection 上改成 `hybrid` schema。

### 3.3 Hybrid 蓝绿重建配置

```dotenv
QDRANT_COLLECTION=local_rag_docs_hybrid_v1
RETRIEVAL_INDEX_SCHEMA=hybrid
RETRIEVAL_MODE=hybrid
DENSE_VECTOR_NAME=dense
SPARSE_VECTOR_NAME=bm25
BM25_MODEL=qdrant/bm25
BM25_TOKENIZER=multilingual
BM25_LANGUAGE=none
HYBRID_FUSION=rrf
HYBRID_PREFETCH_TOP_N=40
```

`retrieval_mode=bm25|hybrid` 只能配合 Hybrid index schema；Hybrid collection 也可临时使用 `retrieval_mode=dense` 做同索引对照实验。

### 3.4 评估 CLI

```bash
python evaluation/run_retrieval_eval.py \
  --dataset evaluation/datasets/golden_retrieval.example.jsonl \
  --top-k 5 \
  --retrieval-mode hybrid \
  --hybrid-fusion rrf \
  --hybrid-prefetch-top-n 40 \
  --experiment-name hybrid-rrf
```

报告记录 collection、index schema、retrieval mode、向量名、BM25 model/tokenizer/language、fusion 和 prefetch，避免将配置不同的结果误当可比实验。

---

## 四、实现细节

### 4.1 同 point 双表示

Hybrid collection 创建一个 named dense vector 和一个 `Modifier.IDF` sparse vector。摄取时每个 `PointStruct` 同时写入 embedding 与 Qdrant BM25 `Document`，并继续复用基于 `document_id + version_id + chunk_index` 的确定性 point ID。

因为两种表示位于同一 point，原有的精确版本删除、激活回滚和 predecessor cleanup 会同时处理 dense 与 sparse，无需引入第二套文档生命周期。

### 4.2 BM25 语义一致性

`app/rag/bm25.py` 是摄取和查询的唯一构造入口，两边使用相同的 model、tokenizer 和 language。默认选择 `multilingual + none`，覆盖中英文混合知识库，并避免摄取/查询 tokenizer 漂移。

Hybrid schema 下，这些影响 lexical 语义的值会进入 pipeline fingerprint；纯查询参数（mode、fusion、prefetch）不进入指纹，因为它们不改变已写入的 point。

### 4.3 融合检索

Hybrid 查询使用 Qdrant `query_points` 的两路 prefetch：

1. named dense vector 执行语义召回；
2. BM25 sparse vector 执行词法召回；
3. Qdrant 使用 RRF（默认）或 DBSF 融合后返回 Top K。

当缺少权重调优证据时，RRF 不依赖 dense cosine 与 BM25 分数处于同一量纲，因此作为更稳妥的默认值。DBSF 保留为评估选项，不宣称默认更优。

### 4.4 Rerank 契约

`RerankCandidate` 的一阶得分字段从特定的 `vector_score` 升级为 `retrieval_score`，因为该分数现在也可能来自 BM25 或 RRF/DBSF。metadata 仍写入 `vector_score` 兼容别名，避免打断旧日志或调试工具。Cross-Encoder 失败时回退到一阶检索排序。

旧 `RERANKER_TYPE=hybrid` 是“一阶得分 + 关键词覆盖”的后置精排，不是 BM25 召回。已使用 Hybrid Retrieval 时不推荐再叠加该策略，以免重复放大 lexical 信号。

---

## 五、依赖

本次无新增 Python 或前端依赖。直接使用已锁定的：

- `qdrant-client==1.17.1`；
- `langchain-qdrant==1.1.0`；
- Compose 中的 `qdrant/qdrant:v1.18.2`。

BM25 推理由 Qdrant 服务端的 `qdrant/bm25` 模型执行，不需要下载本地 Python BM25 词典或模型包。

---

## 六、测试验证

### 6.1 离线回归

```bash
conda activate localrag
python -m compileall app evaluation tests
python -m unittest discover tests/
```

结果：**174 tests, OK**。

新增覆盖：

- 旧 unnamed dense collection 继续走原 LangChain 路径；
- Hybrid schema 下 named dense 查询；
- BM25 multilingual 查询配置；
- RRF 双路 prefetch 和 DBSF 选择；
- dense schema 错配 BM25/hybrid 时快速失败；
- Hybrid collection 同 point 双表示和 IDF schema 校验；
- pipeline fingerprint 区分 dense/hybrid 及 BM25 语义；
- 评估报告保存 Hybrid provenance。

其他交付检查：

- `python -m pip check`：无损坏依赖；
- `npm run lint`：通过；
- `npm run build`：Vite 生产构建通过；
- `docker compose config --quiet`：通过；
- `git diff --check`：通过。

### 6.2 真实 Qdrant 冒烟

使用已锁定的 Qdrant 1.18.2，在隔离临时 collection 中完成两层验证：

1. Qdrant 原生 API 同 point dense + BM25 写入和 RRF 查询成功；
2. 项目 `bulk_upsert_chunks()` 写入后，项目 `retrieve_relevant_documents()` 的 Hybrid 查询成功返回文档与融合分数。

临时 collection 已删除，现有 `local_rag_docs` 与 `qdrant_storage` 保留。这不等价于带真实 embedding 服务和 LLM 的全链路 E2E。

交付时 `local-rag-qdrant` 仍以 `qdrant/qdrant:v1.18.2` 运行，6333/6334 端口已发布。

---

## 七、边界情况与回退

- **默认不迁移**：未新增配置的现有实例继续使用 dense collection。
- **不原地改 schema**：旧 collection 不存在 sparse vector，应新建 collection 全量摄取，避免部分 point 缺少 BM25 表示。
- **schema 失配快速失败**：已有 collection 缺少指定 dense/sparse vector、dense 维度不符或 sparse 未启用 IDF 时拒绝写入。
- **蓝绿回退**：Hybrid 验证失败时，将 collection 和 schema/mode 切回原 `dense/dense` 配置即可。
- **得分不跨策略比较**：dense、BM25、RRF、DBSF 与 Cross-Encoder 分数不在同一量纲。
- **不自动删旧库**：本次没有清空或覆盖用户现有 Qdrant 数据。

---

## 八、影响分析

- **API 影响**：无 HTTP breaking change；来源分数语义拓展为当前检索/精排策略的分数。
- **摄取影响**：Hybrid schema 会对每个 chunk 多写一个 sparse vector；需新 collection 全量重建。
- **查询影响**：Hybrid 比 dense-only 多一路 BM25 prefetch 和 fusion，延迟/召回改善应以 golden dataset 实测。
- **存储影响**：sparse 索引会增加 Qdrant 存储与建索成本，没有新增 SQLite 表。
- **运维影响**：默认配置不变；上线 Hybrid 需新 collection、全量摄取、dense/BM25/hybrid 同数据集评估和可回退切换。
- **评估影响**：报告 provenance 新增检索策略快照；仍使用 `metric_semantics_version=evidence-label-v2`。

---

## 九、后续建议

1. 将生产知识库全量摄取到新 Hybrid collection，不覆盖旧 dense collection；
2. 用同一 golden dataset 分别跑 dense-only、BM25-only、RRF 和 DBSF；
3. 重点增加 API 名、错误码、文件名、中文专有名词和同义改写样本；
4. 同时记录 Recall@K/MRR/NDCG、p95 检索延迟和 Qdrant 存储增量；
5. 只有在评估证明收益后，再将服务配置从旧 collection 切到 Hybrid collection。

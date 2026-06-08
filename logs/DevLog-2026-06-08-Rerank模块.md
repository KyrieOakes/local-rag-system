# Dev Log — Rerank 精排模块

> **日期**: 2026-06-08
> **标签**: feature, rerank, cross-encoder, retrieval, evaluation

---

## 一、概述

在 RAG 管线中新增可插拔的 Rerank 精排层（STEP 3.5），采用 "Vector 粗召回 → Cross-Encoder 精排序" 的经典架构。支持通过 `.env` 配置在不同策略间切换，无需重新摄入文档即可对比效果。

---

## 二、新增/修改的文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/rag/reranker.py` | **新增** | 核心 Rerank 模块：`BaseReranker` 抽象类 + `NoOpReranker` / `CrossEncoderReranker` / `HybridFusionReranker` 三个实现 + `get_reranker()` 工厂函数 |
| `app/core/config.py` | **修改** | 新增 6 个 rerank 配置项（`reranker_type`, `reranker_model`, `reranker_candidate_top_n`, `reranker_final_top_k`, `reranker_max_chars`, `reranker_device`） |
| `.env.example` | **修改** | 新增 rerank 配置说明 |
| `app/services/rag_service.py` | **修改** | `query_rag()` 和 `query_rag_stream()` 中插入 STEP 3.5 Rerank 步骤，含延迟日志 |
| `evaluation/run_retrieval_eval.py` | **修改** | 新增 `--use-reranker`, `--reranker-type`, `--rerank-top-n` CLI 参数 + `_build_reranker()` helper + 报告 `rerank_config` 字段 |
| `evaluation/retrieval_eval_pipeline.ipynb` | **修改** | 新增 rerank 配置打印、`RERANK_ENABLED`/`RERANKER_TYPE`/`RERANK_TOP_N` 运行变量、`run_live_retrieval` 支持 rerank、导出报告含 `rerank_config`、§16 加载报告提取 rerank 配置、对比表显示 "Rerank" 列、rerank vs baseline 自动对比分析 |
| `requirements.txt` | **修改** | 新增 `sentence-transformers` 依赖 |
| `CLAUDE.md` | **修改** | 新增 rerank 架构文档、评估命令、实验矩阵说明 |

---

## 三、架构设计

### 管线变更

```
原:
  STEP 3 → retrieve(top_k=5) → STEP 4 → STEP 5

改:
  STEP 3 → retrieve(top_k=RERANKER_CANDIDATE_TOP_N, e.g. 20)
       → STEP 3.5 → Rerank → keep RERANKER_FINAL_TOP_K (e.g. 5)
       → STEP 4 → STEP 5
```

### Reranker 接口

```python
class BaseReranker(ABC):
    def rerank(query, documents, top_k) -> list[tuple[Document, float]]: ...
```

三种实现：
- **NoOpReranker**: 透传，不做重排（`RERANKER_TYPE=none`）
- **CrossEncoderReranker**: 本地 sentence-transformers Cross-Encoder，懒加载，带 fallback
- **HybridFusionReranker**: 向量分数 + 关键词分数加权融合（`alpha=0.7`），零额外模型依赖

### 配置项

```env
RERANKER_TYPE=none                  # none | cross_encoder | hybrid
RERANKER_MODEL=BAAI/bge-reranker-base
RERANKER_CANDIDATE_TOP_N=20         # Vector Search 召回候选数
RERANKER_FINAL_TOP_K=5              # Rerank 后保留条数
RERANKER_MAX_CHARS=1500             # 每个 doc 送入 Cross-Encoder 的最大字符数
RERANKER_DEVICE=cpu                 # cpu | mps | cuda
```

---

## 四、实现细节

### 懒加载
`CrossEncoderReranker._load_model()` 在首次 `rerank()` 调用时才加载模型，避免服务启动阻塞。模型实例缓存在 `self._model`。

### Fallback
模型加载失败或预测失败时，自动退回 vector-only 结果（按原始分数排序保留 top_k），打印 warning 日志。

### 候选不足跳过
当 `len(documents) <= top_k` 时，直接跳过 rerank，避免无意义开销。

### Metadata 保持
```
doc.metadata["vector_score"] = 原始检索分数
doc.metadata["rerank_score"] = Rerank 分数
doc.metadata["score"] = Rerank 分数（更新为最终分数）
```

### 延迟记录
```
[RAG][STEP 3] 向量检索完成，命中 20 条，耗时 0.120s
[RAG][STEP 3.5] Cross-Encoder 完成，20 → 5 条，耗时 0.850s
```

---

## 五、新依赖

- `sentence-transformers` (含 `transformers`, `torch`, `scikit-learn`, `scipy` 等子依赖)

---

## 六、测试验证

### 单元测试（手动验证）

```bash
conda run -n localrag python -c "
from app.rag.reranker import get_reranker
# 验证 NoOp 模式正常工作
reranker = get_reranker()  # RERANKER_TYPE=none
result = reranker.rerank('test', docs, top_k=3)
# OK
"
```

### 评估 CLI 验证

```bash
# 验证参数解析正常
python -c "from evaluation.run_retrieval_eval import _parse_args; ..."
# OK: use_reranker=True, reranker_type=cross_encoder, rerank_top_n=20
```

---

## 七、边界情况

| 场景 | 处理方式 |
|------|---------|
| 首次加载模型慢 | 懒加载 + 首次请求触发 |
| 模型加载失败 | fallback → vector-only + warning |
| Cross-Encoder 预测失败 | fallback → vector-only + warning |
| 候选 ≤ top_k | 跳过 rerank，直接返回 |
| 文档超长 | 截断到 `RERANKER_MAX_CHARS`（默认 1500） |
| 空候选 | 直接返回空列表 |
| RERANKER_TYPE=none | 完全不变，行为与加入 reranker 前一致 |

---

## 八、影响分析

- **向后兼容**: `RERANKER_TYPE=none`（默认）时，系统行为与之前完全一致
- **延迟增加**: Cross-Encoder 典型延迟 ~500ms–2s（取决于模型和设备），已在日志中记录
- **内存增加**: 加载 BAAI/bge-reranker-base 约 1-2GB
- **评估框架**: 报告 schema 新增可选 `rerank_config` 字段，不影响已有报告的解析

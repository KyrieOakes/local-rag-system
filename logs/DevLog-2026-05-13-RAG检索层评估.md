# Dev Log — RAG 检索层评估体系

> **日期**: 2026-05-13
> **标签**: feature, rag-evaluation, retrieval, metrics, testing

---

## 一、概述

新增一套面向 RAG Retrieval 层的离线评估体系，用于判断系统是否能把正确、少噪声、少重复的上下文检索出来。

本次实现重点不是简单堆几个指标函数，而是建立一个可复用的评估 pipeline：使用 golden dataset 标注标准证据，调用项目现有 retriever 获取真实检索结果，再输出结构化实验报告。该设计适合后续对比不同 chunking、embedding、query rewriting、retriever 或 reranker 策略。

---

## 二、新增/修改的文件清单

### 评估模块（Python）

| 文件 | 操作 | 说明 |
|------|------|------|
| `evaluation/__init__.py` | **新增** | 声明 evaluation 为项目内评估工具包 |
| `evaluation/README.md` | **新增/重写** | 中文说明检索层评估目标、指标体系、golden dataset、chunking 策略对比方式 |
| `evaluation/run_retrieval_eval.py` | **新增** | 检索评估 CLI runner，调用现有 retriever 并输出 JSON 实验报告 |
| `evaluation/retrieval_metrics/__init__.py` | **新增** | 导出检索指标函数 |
| `evaluation/retrieval_metrics/metrics.py` | **新增** | 实现 Recall@K、Precision@K、MRR、NDCG@K、上下文冗余度等指标 |
| `evaluation/retrieval_metrics/matching.py` | **新增** | 将 golden dataset 中的 source/snippet 标注映射到当前检索 chunk |
| `evaluation/retrieval_metrics/evaluator.py` | **新增** | 统一评估入口，按 `core_metrics` 和 `context_quality` 输出结果 |
| `evaluation/datasets/golden_retrieval.example.jsonl` | **新增** | 提供 golden dataset 示例格式 |

### 测试（Python unittest）

| 文件 | 操作 | 说明 |
|------|------|------|
| `tests/test_retrieval_metrics.py` | **新增** | 覆盖核心指标、上下文冗余度、边界输入 |
| `tests/test_retrieval_matching.py` | **新增** | 覆盖 file_path/source/snippet 匹配逻辑 |
| `tests/test_retrieval_evaluator.py` | **新增** | 覆盖统一 evaluator 输出结构和典型检索质量场景 |

---

## 三、CLI 设计

### `evaluation/run_retrieval_eval.py`

用于运行离线检索评估。

**命令示例**:

```bash
conda activate localrag
python evaluation/run_retrieval_eval.py \
  --dataset evaluation/datasets/golden_retrieval.example.jsonl \
  --top-k 5 \
  --experiment-name recursive-800-120
```

**可选 query processor 评估**:

```bash
python evaluation/run_retrieval_eval.py \
  --dataset evaluation/datasets/golden_retrieval.example.jsonl \
  --top-k 5 \
  --experiment-name recursive-800-120-query-processor \
  --use-query-processor
```

**主要参数**:

| 参数 | 说明 |
|------|------|
| `--dataset` | golden retrieval JSONL 数据集路径 |
| `--top-k` | 评估 top-k 检索结果 |
| `--experiment-name` | 当前实验名称，建议包含 chunking 策略 |
| `--output-dir` | 报告输出目录，默认 `evaluation/results` |
| `--use-query-processor` | 是否把 query rewriting 纳入评估 |

**输出位置**:

```text
evaluation/results/<experiment-name>.json
```

---

## 四、实现细节

### 4.1 评估 Pipeline

完整流程如下：

```text
golden dataset
    ↓
读取每个 question
    ↓
可选：query_processor 做 query rewriting
    ↓
调用现有 retrieve_relevant_documents
    ↓
将 LangChain Document 转成 RetrievedItem
    ↓
使用 relevant_sources 做 source/snippet-aware 匹配
    ↓
计算 core_metrics + context_quality
    ↓
输出 retrieval-eval-v1 JSON 报告
```

该流程直接复用项目现有 `app.rag.retriever.retrieve_relevant_documents()`，因此评估的是当前 Qdrant collection 和 embedding 配置下的真实检索效果。

### 4.2 Golden Dataset 标注方式

示例：

```json
{"id":"q1","question":"How does the retrieval pipeline work?","relevant_sources":[{"file_path":"data/engineering/ai/search/_index.md","text":"retrieval","relevance":2}]}
```

字段说明：

- `question`: 检索问题。
- `relevant_sources`: 人工标注的相关证据列表。
- `file_path`: 推荐使用的稳定来源字段。
- `source` / `file_name`: 用于兼容上传文件名或展示名。
- `text`: 可选文本片段，用于避免只按文件命中过宽。
- `relevance`: 分级相关性分数，用于 `NDCG@K`。

本设计不把 `chunk_index` 作为 golden dataset 的核心标注，因为切换 chunking 策略后 chunk 边界和 index 会变化。企业评估更常见的做法是标注稳定证据来源，例如 document/source/span/snippet，再映射到当前策略生成的 chunk。

### 4.3 指标层 (`evaluation/retrieval_metrics/metrics.py`)

核心检索指标：

- `recall_at_k()`：衡量正确证据是否被召回。
- `precision_at_k()`：衡量 top-k 上下文中有多少是有用内容。
- `mrr()` / `mean_reciprocal_rank()`：衡量正确结果排得是否靠前。
- `ndcg_at_k()`：支持二元相关性和分级相关性，衡量高价值证据是否排在前面。

上下文质量指标：

- `context_redundancy_at_k()`：综合统计无关和重复上下文比例。
- `irrelevant_rate@K`：top-k 中未命中标注证据的比例。
- `duplicate_rate@K`：top-k 中重复上下文比例。

### 4.4 匹配层 (`evaluation/retrieval_metrics/matching.py`)

匹配层负责把人工标注的 `relevant_sources` 映射为当前检索结果中的具体 chunk ID。

支持：

- 按 `file_path` 匹配。
- 按 `source` / `file_name` 匹配上传文档。
- 按 `text` snippet 匹配 chunk 内容。
- snippet 匹配对大小写和空白变化做容错。
- 当 `chunk_index` 缺失时，使用内容 hash 生成稳定评估 ID。

如果某条标注证据完全没有被检索到，会保留一个 `expected:<index>` 虚拟项用于 NDCG 的 ideal ranking，避免漏召回场景被错误低估。

### 4.5 统一评估层 (`evaluation/retrieval_metrics/evaluator.py`)

`evaluate_retrieval_case()` 是单条 query 的统一入口，输出：

```json
{
  "core_metrics": {
    "recall@5": 0.8,
    "precision@5": 0.4,
    "mrr": 1.0,
    "ndcg@5": 0.72
  },
  "context_quality": {
    "context_redundancy@5": 0.4,
    "irrelevant_rate@5": 0.4,
    "duplicate_rate@5": 0.0
  }
}
```

这种结构区分“找没找到正确文档”和“上下文窗口是否干净”，更适合企业内部评估报告和后续 dashboard 展示。

---

## 五、新增依赖

本次没有新增 Python 或前端依赖。

说明：

- 当前实现只使用 Python 标准库和项目已有 RAG 代码。
- 如果后续决定接入 LangChain Evaluators、LlamaIndex Evals 或 Haystack Eval，应安装到 conda `localrag` 环境，而不是全局 Python。

示例：

```bash
conda activate localrag
pip install <eval-package>
```

---

## 六、测试验证

### 自动化测试

运行：

```bash
python -m unittest tests/test_retrieval_metrics.py tests/test_retrieval_matching.py tests/test_retrieval_evaluator.py
```

结果：

```text
Ran 25 tests in 0.000s
OK
```

### 语法检查

运行：

```bash
python -m py_compile \
  evaluation/run_retrieval_eval.py \
  evaluation/retrieval_metrics/evaluator.py \
  evaluation/retrieval_metrics/matching.py \
  evaluation/retrieval_metrics/metrics.py
```

结果：通过，无语法错误。

### 重点测试场景

- 正确文档在 top-k 外时，`Recall@K` 从 0 到 1 的变化。
- top-k 中混入午餐菜单、假期日历等噪声时，`Precision@K` 被惩罚。
- 重复 SSO password reset chunk 时，`duplicate_rate@K` 上升。
- 错文件中出现相同 snippet 时，不算命中。
- 上传文件只靠 `source` / `file_name` 也能匹配。
- snippet 匹配支持大小写和空白容错。
- 完全 miss 时，Recall、Precision、MRR 都为 0，`irrelevant_rate@K` 为 1。
- 分级相关性下，`NDCG@K` 能奖励高价值证据排在前面。

---

## 七、边界情况

- 当前模块只评估 Retrieval 层，不评估 LLM 生成答案质量。
- 评估脚本不会自动切换 chunking 策略，也不会自动清理或重建 Qdrant collection。
- 每次对比 chunking 策略前，需要先用现有 ingestion 流程重新摄入同一批文档。
- `run_retrieval_eval.py` 依赖当前 Qdrant、embedding 服务和 `.env` 配置可用。
- 示例 golden dataset 只是格式模板，真实评估需要人工维护更完整的标注集。

---

## 八、与现有系统的影响

- **无 API 破坏性变更**: 未修改 FastAPI 路由、请求结构或响应结构。
- **无前端影响**: 未修改 React/Vite 前端逻辑。
- **无新增依赖**: 不影响部署依赖和 conda 环境。
- **可独立运行**: evaluation 模块作为离线评估工具存在，不影响正常 RAG 查询流程。
- **支持策略对比**: 后续可以通过不同 `experiment-name` 保存多份报告，对比 chunking、embedding、query rewriting、retriever 或 reranker 策略效果。

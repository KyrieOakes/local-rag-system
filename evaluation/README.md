# RAG 检索层评估

这个目录用于评估 RAG 的 Retrieval 层：重点回答一个问题，系统到底有没有把正确、少噪声、少重复的上下文找出来。

当前实现对齐企业里常见的检索评估方式：先建立稳定的 golden dataset，再对每次 chunking / embedding / retriever 策略生成标准化报告。它不是临时拼指标，而是一个可持续比较实验结果的 retrieval evaluation harness。

## 评估范围

本阶段只评估检索层，不评估 LLM 最终答案。

检索层关注：

- 正确参考文档是否被召回。
- 正确文档是否排在前面。
- Top K 上下文里有多少真正有用。
- 是否混入无关、重复、噪声文档。

后续如果要评估答案质量，可以在这个基础上增加 generation 层指标，例如 faithfulness、answer relevance、citation correctness。

## 指标体系

核心检索指标：

- `Recall@K`：正确参考文档是否出现在 top-k 里，衡量“有没有找回来”。
- `Precision@K`：top-k 里有多少是有用内容，衡量“上下文有多干净”。
- `MRR`：第一个正确文档的倒数排名，衡量“正确内容排得靠不靠前”。
- `NDCG@K`：考虑排序位置和分级相关性的检索质量，适合给关键证据更高权重。

上下文质量指标：

- `context_redundancy@K`：top-k 中无关或重复上下文的综合比例。
- `irrelevant_rate@K`：top-k 中未命中标注相关证据的比例。
- `duplicate_rate@K`：top-k 中重复上下文的比例。

这些指标会在报告中分成两组：

```json
{
  "aggregate": {
    "core_metrics": {
      "recall@5": 0.8,
      "precision@5": 0.36,
      "mrr": 0.74,
      "ndcg@5": 0.69
    },
    "context_quality": {
      "context_redundancy@5": 0.44,
      "irrelevant_rate@5": 0.4,
      "duplicate_rate@5": 0.04
    }
  }
}
```

## 目录结构

```text
evaluation/
├── README.md
├── run_retrieval_eval.py
├── datasets/
│   └── golden_retrieval.example.jsonl
├── results/
│   └── <experiment-name>.json
└── retrieval_metrics/
    ├── evaluator.py
    ├── matching.py
    └── metrics.py
```

## Golden Dataset

检索评估的关键不是写公式，而是建立可复用的标注集。数据集使用 JSONL，每行一个问题：

```json
{"id":"q1","question":"How does the retrieval pipeline work?","relevant_sources":[{"file_path":"data/engineering/ai/search/_index.md","text":"retrieval","relevance":2}]}
```

字段说明：

- `id`：评估样本 ID，建议稳定且可读。
- `question`：检索问题。
- `relevant_sources`：人工标注的相关证据列表。
- `file_path`：相关证据所在文件路径，推荐填写。
- `source` / `file_name`：可选，用于匹配上传文件名或展示名。
- `text`：可选的相关文本片段。切换 chunking 策略时，片段匹配比固定 `chunk_index` 更稳定。
- `relevance`：可选的分级相关性分数，默认 `1.0`。用于 `NDCG@K`。

为什么不用固定 `chunk_index` 做唯一标准：chunking 策略变化后，chunk 数量、边界和 index 都会变化。企业评估更常用稳定证据标注，例如 source/document/span/snippet，再映射到当前策略生成的 chunk。

## 运行方式

建议在项目指定的 conda 环境里运行。以后如果需要安装 LangChain/LlamaIndex/Haystack 相关评估包，也应该安装到 `localrag` 环境，而不是全局 Python：

```bash
conda activate localrag
```

运行检索评估：

```bash
python evaluation/run_retrieval_eval.py \
  --dataset evaluation/datasets/golden_retrieval.example.jsonl \
  --top-k 5 \
  --experiment-name recursive-800-120
```

如果要把 query rewriting 也纳入检索评估：

```bash
python evaluation/run_retrieval_eval.py \
  --dataset evaluation/datasets/golden_retrieval.example.jsonl \
  --top-k 5 \
  --experiment-name recursive-800-120-query-processor \
  --use-query-processor
```

报告会写入：

```text
evaluation/results/<experiment-name>.json
```

## 如何评估 chunking 策略

每次比较 chunking 策略时，保持变量清晰：

1. 固定同一批原始文档。
2. 固定同一份 golden dataset。
3. 修改 chunking 策略，例如 `chunk_size`、`chunk_overlap`、Markdown header splitter。
4. 清理并重新摄入文档，让 Qdrant collection 只包含当前策略生成的 chunk。
5. 跑 `run_retrieval_eval.py`，保存带策略名的实验报告。
6. 对比不同报告里的 `aggregate.core_metrics` 和 `aggregate.context_quality`。

示例实验命名：

```text
recursive-800-120
recursive-1000-150
markdown-header-recursive-800-120
```

推荐判断方式：

- `Recall@K` 高但 `Precision@K` 低：能找回来，但上下文噪声偏多。
- `Precision@K` 高但 `Recall@K` 低：上下文干净，但漏召回风险大。
- `MRR` 低：正确证据排得靠后，容易被 LLM 忽略。
- `context_redundancy@K` 高：top-k 里无关或重复内容太多，可能浪费上下文窗口。
- `NDCG@K` 高：高价值证据排得靠前，排序质量更好。

## 和常用企业工具的关系

业界常见选择包括：

- LangChain Evaluators
- LlamaIndex Evals
- Haystack Eval

这些工具适合接入更大的评估平台、trace 系统或完整 RAG pipeline。当前项目先保留轻量但标准化的本地评估 harness，原因是：

- 不强制引入额外依赖，当前代码可以直接在本项目测试。
- 输出 JSON 报告结构稳定，后续可以接 CI、dashboard 或实验追踪。
- golden dataset schema 与主流框架理念一致，后续迁移到 LangChain/LlamaIndex/Haystack 时，不需要推倒重来。

如果后续决定引入第三方 eval 包，请安装到 conda `localrag` 环境，例如：

```bash
conda activate localrag
pip install <eval-package>
```

当前这版没有新增下载依赖。

## 当前边界

这个模块负责离线检索评估，不负责自动切换 chunking 策略，也不负责自动重建 Qdrant collection。策略切换、清理 collection、重新摄入文档仍由现有 ingestion 流程负责。


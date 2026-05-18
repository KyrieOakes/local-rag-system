"""
retrieval_metrics 子包 — 检索质量指标计算。

公开的指标函数：
- recall_at_k — 召回率@K：前 K 个结果中找到的相关文档占比
- precision_at_k — 精确率@K：前 K 个结果中相关文档的比例
- mrr / reciprocal_rank / mean_reciprocal_rank — 倒数排名（首个相关文档的排名倒数）
- ndcg_at_k — 归一化折损累计增益@K（支持二值和分级相关性）
- context_redundancy_at_k — 上下文冗余度@K（不相关率 + 重复率）
"""

from evaluation.retrieval_metrics.metrics import (
    context_redundancy_at_k,
    mean_reciprocal_rank,
    mrr,
    ndcg_at_k,
    precision_at_k,
    reciprocal_rank,
    recall_at_k,
)

__all__ = [
    "context_redundancy_at_k",
    "mean_reciprocal_rank",
    "mrr",
    "ndcg_at_k",
    "precision_at_k",
    "reciprocal_rank",
    "recall_at_k",
]

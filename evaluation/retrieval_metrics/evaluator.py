from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from evaluation.retrieval_metrics.matching import RetrievedItem, RelevantSource, match_retrieved_to_relevant_sources
from evaluation.retrieval_metrics.metrics import (
    context_redundancy_at_k,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


@dataclass(frozen=True)
class RetrievalEvaluationResult:
    core_metrics: dict[str, float]
    context_quality: dict[str, float]
    matched_relevant_ids: list[str]
    retrieved_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "core_metrics": self.core_metrics,
            "context_quality": self.context_quality,
            "matched_relevant_ids": self.matched_relevant_ids,
            "retrieved_ids": self.retrieved_ids,
        }


def evaluate_retrieval_case(
    retrieved_items: Sequence[RetrievedItem],
    relevant_sources: Sequence[RelevantSource],
    k: int,
) -> RetrievalEvaluationResult:
    """Evaluate one retrieval case using enterprise-style retrieval categories."""
    matched = match_retrieved_to_relevant_sources(retrieved_items, relevant_sources)
    context_keys = [_context_key(item) for item in retrieved_items]

    core_metrics = {
        f"recall@{k}": recall_at_k(matched.retrieved_ids, matched.relevant_ids, k),
        f"precision@{k}": precision_at_k(matched.retrieved_ids, matched.relevant_ids, k),
        "mrr": mrr(matched.retrieved_ids, matched.relevant_ids),
        f"ndcg@{k}": ndcg_at_k(
            matched.retrieved_ids,
            k=k,
            relevance_scores=matched.relevance_scores,
        ),
    }

    context_quality = context_redundancy_at_k(
        matched.retrieved_ids,
        matched.relevant_ids,
        k,
        context_keys=context_keys,
    )

    return RetrievalEvaluationResult(
        core_metrics=core_metrics,
        context_quality=context_quality,
        matched_relevant_ids=sorted(matched.relevant_ids),
        retrieved_ids=matched.retrieved_ids,
    )


def _context_key(item: RetrievedItem) -> str:
    metadata: Mapping[str, Any] = item.metadata
    file_path = metadata.get("file_path") or metadata.get("source") or "unknown"
    normalized_content = " ".join(item.content.casefold().split())
    return f"{file_path}:{normalized_content[:500]}"


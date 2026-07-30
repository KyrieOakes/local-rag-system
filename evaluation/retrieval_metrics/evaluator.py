"""
统一评估器模块。

evaluate_retrieval_case() 将一个检索案例的评估流程封装为一次调用：
1. 调用 match_retrieved_to_relevant_sources() 匹配检索结果与标注
2. 计算 core_metrics（4 项）：
   - recall@K, precision@K, MRR, NDCG@K
3. 计算 context_quality（3 项）：
   - context_redundancy@K, irrelevant_rate@K, duplicate_rate@K

返回 RetrievalEvaluationResult 数据类，包含分组指标和匹配信息。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from evaluation.retrieval_metrics.matching import RetrievedItem, RelevantSource, match_retrieved_to_relevant_sources
from evaluation.retrieval_metrics.metrics import (
    context_redundancy_at_k,
    ndcg_at_k,
)


@dataclass(frozen=True)
class RetrievalEvaluationResult:
    core_metrics: dict[str, float]
    context_quality: dict[str, float]
    matched_relevant_ids: list[str]
    gold_evidence_ids: list[str]
    retrieved_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "core_metrics": self.core_metrics,
            "context_quality": self.context_quality,
            # Keep the legacy key for report/notebook compatibility. Its values
            # are stable evidence IDs in new reports, rather than chunk IDs.
            "matched_relevant_ids": self.matched_relevant_ids,
            "matched_evidence_ids": self.matched_relevant_ids,
            "gold_evidence_ids": self.gold_evidence_ids,
            "retrieved_ids": self.retrieved_ids,
        }


def evaluate_retrieval_case(
    retrieved_items: Sequence[RetrievedItem],
    relevant_sources: Sequence[RelevantSource],
    k: int,
) -> RetrievalEvaluationResult:
    """Evaluate one retrieval case using enterprise-style retrieval categories."""
    if k <= 0:
        raise ValueError("k must be greater than 0")

    matched = match_retrieved_to_relevant_sources(retrieved_items, relevant_sources)
    context_keys = [_context_key(item) for item in retrieved_items]
    top_matches = matched.evidence_matches_by_rank[:k]
    ranked_evidence_ids = _ranked_unique_evidence_ids(top_matches)
    matched_evidence_ids = set(ranked_evidence_ids)
    ranked_evidence_slots = _ranked_evidence_slots(
        top_matches,
        matched.evidence_scores,
    )

    recall = (
        len(matched_evidence_ids) / len(matched.evidence_ids)
        if matched.evidence_ids
        else 0.0
    )
    # Precision remains retrieval-slot based: one chunk counts at most once,
    # and repeated chunks for evidence already seen do not inflate the score.
    precision = (
        sum(
            1
            for slot in ranked_evidence_slots
            if slot in matched.evidence_scores
        )
        / k
    )
    reciprocal_rank = next(
        (
            1 / rank
            for rank, evidence_ids in enumerate(
                matched.evidence_matches_by_rank,
                start=1,
            )
            if evidence_ids
        ),
        0.0,
    )

    core_metrics = {
        f"recall@{k}": recall,
        f"precision@{k}": precision,
        "mrr": reciprocal_rank,
        f"ndcg@{k}": ndcg_at_k(
            ranked_evidence_slots,
            k=k,
            relevance_scores=matched.evidence_scores,
        ),
    }

    context_quality = context_redundancy_at_k(
        matched.retrieved_ids,
        matched.matched_chunk_ids,
        k,
        context_keys=context_keys,
    )

    return RetrievalEvaluationResult(
        core_metrics=core_metrics,
        context_quality=context_quality,
        matched_relevant_ids=sorted(matched_evidence_ids),
        gold_evidence_ids=matched.evidence_ids,
        retrieved_ids=matched.retrieved_ids,
    )


def _ranked_unique_evidence_ids(
    evidence_matches_by_rank: Sequence[Sequence[str]],
) -> list[str]:
    """Flatten first evidence hits in retrieval order without double counting."""
    ranked = []
    seen = set()
    for matches in evidence_matches_by_rank:
        for evidence_id in matches:
            if evidence_id not in seen:
                seen.add(evidence_id)
                ranked.append(evidence_id)
    return ranked


def _ranked_evidence_slots(
    evidence_matches_by_rank: Sequence[Sequence[str]],
    evidence_scores: Mapping[str, float],
) -> list[str]:
    """Preserve retrieval ranks while de-duplicating evidence for NDCG.

    A retrieved chunk can cover multiple evidence labels, but it occupies one
    ranked slot. The highest-relevance unseen label represents that slot; noise
    and duplicate-only chunks receive a zero-relevance sentinel.
    """
    slots = []
    seen = set()
    for rank, matches in enumerate(evidence_matches_by_rank):
        unseen = [evidence_id for evidence_id in matches if evidence_id not in seen]
        if unseen:
            chosen = max(
                unseen,
                key=lambda evidence_id: evidence_scores.get(evidence_id, 0.0),
            )
            seen.update(unseen)
            slots.append(chosen)
        else:
            slots.append(f"__no_new_evidence_at_rank_{rank}")
    return slots


def _context_key(item: RetrievedItem) -> str:
    metadata: Mapping[str, Any] = item.metadata
    file_path = metadata.get("file_path") or metadata.get("source") or "unknown"
    normalized_content = " ".join(item.content.casefold().split())
    return f"{file_path}:{normalized_content[:500]}"

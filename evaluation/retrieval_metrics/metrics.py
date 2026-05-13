from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import TypeAlias

DocumentId: TypeAlias = str | int
RelevanceScores: TypeAlias = Mapping[DocumentId, float]


def _validate_k(k: int) -> None:
    if k <= 0:
        raise ValueError("k must be greater than 0")


def _top_k(retrieved_ids: Sequence[DocumentId], k: int) -> list[DocumentId]:
    _validate_k(k)
    return list(retrieved_ids[:k])


def recall_at_k(
    retrieved_ids: Sequence[DocumentId],
    relevant_ids: set[DocumentId] | Sequence[DocumentId],
    k: int,
) -> float:
    """Return the fraction of relevant documents found in the top K results."""
    relevant_set = set(relevant_ids)
    if not relevant_set:
        return 0.0

    hits = sum(1 for document_id in _top_k(retrieved_ids, k) if document_id in relevant_set)
    return hits / len(relevant_set)


def precision_at_k(
    retrieved_ids: Sequence[DocumentId],
    relevant_ids: set[DocumentId] | Sequence[DocumentId],
    k: int,
) -> float:
    """Return the fraction of top K results that are relevant."""
    top_results = _top_k(retrieved_ids, k)
    if not top_results:
        return 0.0

    relevant_set = set(relevant_ids)
    hits = sum(1 for document_id in top_results if document_id in relevant_set)
    return hits / k


def context_redundancy_at_k(
    retrieved_ids: Sequence[DocumentId],
    relevant_ids: set[DocumentId] | Sequence[DocumentId],
    k: int,
    context_keys: Sequence[str] | None = None,
) -> dict[str, float]:
    """Return context redundancy signals for top K retrieved contexts.

    `irrelevant_rate@k` captures noise: retrieved contexts that are not labeled
    as useful. `duplicate_rate@k` captures repeated contexts by ID or by an
    optional caller-provided context key. `context_redundancy@k` is the combined
    rate of noisy or repeated contexts, capped at 1.0.
    """
    top_results = _top_k(retrieved_ids, k)
    if not top_results:
        return {
            f"context_redundancy@{k}": 0.0,
            f"irrelevant_rate@{k}": 0.0,
            f"duplicate_rate@{k}": 0.0,
        }

    relevant_set = set(relevant_ids)
    irrelevant_count = sum(1 for document_id in top_results if document_id not in relevant_set)

    duplicate_basis = list(context_keys[:k]) if context_keys is not None else [str(item) for item in top_results]
    duplicate_count = len(duplicate_basis) - len(set(duplicate_basis))

    redundancy_count = min(k, irrelevant_count + duplicate_count)
    return {
        f"context_redundancy@{k}": redundancy_count / k,
        f"irrelevant_rate@{k}": irrelevant_count / k,
        f"duplicate_rate@{k}": duplicate_count / k,
    }


def mrr(
    retrieved_ids: Sequence[DocumentId],
    relevant_ids: set[DocumentId] | Sequence[DocumentId],
) -> float:
    """Return reciprocal rank for one ranked retrieval result list.

    This single-query form is kept as a convenient alias for
    `reciprocal_rank`. For a dataset-level mean, use
    `mean_reciprocal_rank`.
    """
    return reciprocal_rank(retrieved_ids, relevant_ids)


def reciprocal_rank(
    retrieved_ids: Sequence[DocumentId],
    relevant_ids: set[DocumentId] | Sequence[DocumentId],
) -> float:
    """Return reciprocal rank of the first relevant retrieval result."""
    relevant_set = set(relevant_ids)
    if not relevant_set:
        return 0.0

    for rank, document_id in enumerate(retrieved_ids, start=1):
        if document_id in relevant_set:
            return 1 / rank

    return 0.0


def mean_reciprocal_rank(
    retrieved_id_lists: Sequence[Sequence[DocumentId]],
    relevant_id_lists: Sequence[set[DocumentId] | Sequence[DocumentId]],
) -> float:
    """Return Mean Reciprocal Rank across multiple retrieval queries."""
    if len(retrieved_id_lists) != len(relevant_id_lists):
        raise ValueError("retrieved_id_lists and relevant_id_lists must have the same length")

    if not retrieved_id_lists:
        return 0.0

    reciprocal_ranks = [
        reciprocal_rank(retrieved_ids, relevant_ids)
        for retrieved_ids, relevant_ids in zip(retrieved_id_lists, relevant_id_lists)
    ]
    return sum(reciprocal_ranks) / len(reciprocal_ranks)


def ndcg_at_k(
    retrieved_ids: Sequence[DocumentId],
    relevant_ids: set[DocumentId] | Sequence[DocumentId] | None = None,
    k: int = 10,
    relevance_scores: RelevanceScores | None = None,
) -> float:
    """Return Normalized Discounted Cumulative Gain at K.

    If `relevance_scores` is not provided, each item in `relevant_ids` receives
    a binary relevance score of 1.0.
    """
    _validate_k(k)
    scores = _build_relevance_scores(relevant_ids, relevance_scores)
    if not scores:
        return 0.0

    dcg = _dcg([scores.get(document_id, 0.0) for document_id in retrieved_ids[:k]])
    ideal_relevances = sorted(scores.values(), reverse=True)[:k]
    ideal_dcg = _dcg(ideal_relevances)

    if ideal_dcg == 0:
        return 0.0

    return dcg / ideal_dcg


def _build_relevance_scores(
    relevant_ids: set[DocumentId] | Sequence[DocumentId] | None,
    relevance_scores: RelevanceScores | None,
) -> dict[DocumentId, float]:
    if relevance_scores is not None:
        return {document_id: float(score) for document_id, score in relevance_scores.items()}

    if relevant_ids is None:
        return {}

    return {document_id: 1.0 for document_id in relevant_ids}


def _dcg(relevances: Sequence[float]) -> float:
    return sum(
        ((2**relevance) - 1) / math.log2(rank + 1)
        for rank, relevance in enumerate(relevances, start=1)
    )

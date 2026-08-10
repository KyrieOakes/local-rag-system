"""Dense, BM25, and fused Qdrant retrieval behind one stable contract."""

import logging
import time

from langchain_core.documents import Document
from qdrant_client import models

from app.core.config import settings
from app.rag.bm25 import build_bm25_document
from app.rag.embeddings import get_embedding_model
from app.rag.vectorstore import get_qdrant_client, get_vectorstore

logger = logging.getLogger(__name__)


def _validate_retrieval_request(mode: str, top_k: int) -> None:
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    if mode not in {"dense", "bm25", "hybrid"}:
        raise ValueError(f"Unsupported retrieval mode: {mode}")
    if mode in {"bm25", "hybrid"} and settings.retrieval_index_schema != "hybrid":
        raise ValueError(
            f"Retrieval mode {mode!r} requires RETRIEVAL_INDEX_SCHEMA=hybrid"
        )


def _scored_points_to_results(points: list) -> list[tuple[Document, float]]:
    results: list[tuple[Document, float]] = []
    for point in points:
        payload = point.payload or {}
        content = payload.get("page_content")
        metadata = payload.get("metadata") or {}
        if not isinstance(content, str) or not isinstance(metadata, dict):
            raise ValueError(
                f"Qdrant point {point.id!s} is missing the expected RAG payload"
            )
        results.append(
            (
                Document(page_content=content, metadata=dict(metadata)),
                float(point.score),
            )
        )
    return results


def _query_points(
    *,
    query,
    top_k: int,
    using: str | None = None,
    prefetch: list[models.Prefetch] | None = None,
) -> list[tuple[Document, float]]:
    response = get_qdrant_client().query_points(
        collection_name=settings.qdrant_collection,
        query=query,
        using=using,
        prefetch=prefetch,
        limit=top_k,
        with_payload=True,
        with_vectors=False,
    )
    return _scored_points_to_results(list(response.points))


def _dense_search(question: str, top_k: int) -> list[tuple[Document, float]]:
    if settings.retrieval_index_schema == "dense":
        return get_vectorstore().similarity_search_with_score(
            query=question,
            k=top_k,
        )
    dense_query = get_embedding_model().embed_query(question)
    return _query_points(
        query=dense_query,
        using=settings.dense_vector_name,
        top_k=top_k,
    )


def _bm25_search(question: str, top_k: int) -> list[tuple[Document, float]]:
    return _query_points(
        query=build_bm25_document(question),
        using=settings.sparse_vector_name,
        top_k=top_k,
    )


def _fusion_query(fusion: str):
    if fusion == "rrf":
        return models.RrfQuery(rrf=models.Rrf())
    if fusion == "dbsf":
        return models.FusionQuery(fusion=models.Fusion.DBSF)
    raise ValueError(f"Unsupported hybrid fusion: {fusion}")


def _hybrid_search(
    question: str,
    top_k: int,
    *,
    fusion: str,
    prefetch_top_n: int,
) -> list[tuple[Document, float]]:
    dense_query = get_embedding_model().embed_query(question)
    prefetch_k = max(top_k, prefetch_top_n)
    return _query_points(
        query=_fusion_query(fusion),
        prefetch=[
            models.Prefetch(
                query=dense_query,
                using=settings.dense_vector_name,
                limit=prefetch_k,
            ),
            models.Prefetch(
                query=build_bm25_document(question),
                using=settings.sparse_vector_name,
                limit=prefetch_k,
            ),
        ],
        top_k=top_k,
    )


def retrieve_relevant_documents(
    question: str,
    top_k: int = 5,
    *,
    mode: str | None = None,
    hybrid_fusion: str | None = None,
    hybrid_prefetch_top_n: int | None = None,
) -> list[tuple[Document, float]]:
    """Retrieve ranked chunks while preserving ``(Document, score)`` callers."""
    effective_mode = mode or settings.retrieval_mode
    _validate_retrieval_request(effective_mode, top_k)
    step_start = time.perf_counter()
    logger.info(
        "[RAG][RETRIEVAL] 开始 mode=%s top_k=%d",
        effective_mode,
        top_k,
    )

    if effective_mode == "dense":
        results = _dense_search(question, top_k)
    elif effective_mode == "bm25":
        results = _bm25_search(question, top_k)
    else:
        results = _hybrid_search(
            question,
            top_k,
            fusion=hybrid_fusion or settings.hybrid_fusion,
            prefetch_top_n=(
                hybrid_prefetch_top_n
                if hybrid_prefetch_top_n is not None
                else settings.hybrid_prefetch_top_n
            ),
        )

    logger.info(
        "[RAG][RETRIEVAL] 完成 mode=%s 命中=%d 耗时=%.3fs",
        effective_mode,
        len(results),
        time.perf_counter() - step_start,
    )
    return results

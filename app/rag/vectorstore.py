"""Cached Qdrant access for retrieval plus legacy compatibility wrappers."""

import warnings
from functools import lru_cache

from qdrant_client import QdrantClient
from langchain_qdrant import QdrantVectorStore

from app.core.config import settings
from app.rag.embeddings import get_embedding_model
from app.rag.ingestion.bulk_writer import (
    delete_chunks_by_source,
    list_indexed_documents,
)


@lru_cache(maxsize=8)
def _build_qdrant_client(url: str) -> QdrantClient:
    return QdrantClient(url=url)


def _get_qdrant_client() -> QdrantClient:
    """Reuse the transport client for the effective Qdrant URL."""
    return _build_qdrant_client(settings.qdrant_url)


@lru_cache(maxsize=8)
def _build_vectorstore(
    qdrant_url: str,
    collection_name: str,
    embedding_base_url: str,
    embedding_model: str,
) -> QdrantVectorStore:
    return QdrantVectorStore.from_existing_collection(
        embedding=get_embedding_model(),
        collection_name=collection_name,
        url=qdrant_url,
    )


def get_vectorstore() -> QdrantVectorStore:
    """Reuse a LangChain vector-store wrapper per effective configuration."""
    return _build_vectorstore(
        settings.qdrant_url,
        settings.qdrant_collection,
        settings.embedding_base_url,
        settings.embedding_model,
    )


def create_vectorstore_from_documents(documents):
    """Deprecated write path; use the versioned ingestion pipeline instead."""
    warnings.warn(
        "create_vectorstore_from_documents is deprecated; use ingest_file_paths",
        DeprecationWarning,
        stacklevel=2,
    )
    embedding_model = get_embedding_model()

    return QdrantVectorStore.from_documents(
        documents=documents,
        embedding=embedding_model,
        collection_name=settings.qdrant_collection,
        url=settings.qdrant_url,
        force_recreate=False,
    )


def list_all_documents() -> list[dict]:
    """Compatibility alias for the document-ID-aware listing implementation."""
    return list_indexed_documents(settings.qdrant_collection)


def delete_document_by_source(source: str) -> int:
    """Deprecated unsafe source-wide delete retained for legacy callers."""
    warnings.warn(
        "delete_document_by_source may affect same-name legacy documents; "
        "use document_service.delete_document with a document_id",
        DeprecationWarning,
        stacklevel=2,
    )
    return delete_chunks_by_source(source, settings.qdrant_collection)

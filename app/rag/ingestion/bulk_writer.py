"""Low-level Qdrant writes, version cleanup, and document inspection."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import settings
from app.rag.ingestion.checksum_store import make_legacy_document_id

logger = logging.getLogger(__name__)

# Qdrant has a 32 MB payload limit per upsert call.
UPSERT_BATCH_SIZE = 500
POINT_ID_NAMESPACE = uuid.UUID("15ab3d6b-6638-41ae-a4d4-a786e43eaab7")


def _get_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


def _condition(field: str, value: str) -> FieldCondition:
    return FieldCondition(
        key=f"metadata.{field}",
        match=MatchValue(value=value),
    )


def _make_point_id(
    document_id: str,
    version_id: str,
    chunk_index: int,
) -> str:
    """Build a deterministic point ID scoped to a document pipeline version."""
    return str(
        uuid.uuid5(
            POINT_ID_NAMESPACE,
            f"{document_id}\0{version_id}\0{chunk_index}",
        )
    )


def _delete_by_filter(
    scroll_filter: Filter,
    collection_name: str,
) -> int:
    client = _get_client()
    if not client.collection_exists(collection_name=collection_name):
        return 0

    count_result = client.count(
        collection_name=collection_name,
        count_filter=scroll_filter,
        exact=True,
    )
    matched = count_result.count
    if matched == 0:
        return 0

    client.delete(
        collection_name=collection_name,
        points_selector=scroll_filter,
        wait=True,
    )
    return matched


def delete_chunks_by_filepath(
    file_path: str,
    collection_name: str | None = None,
) -> int:
    """Delete all indexed versions whose legacy ``file_path`` matches exactly."""
    collection = collection_name or settings.qdrant_collection
    matched = _delete_by_filter(
        Filter(must=[_condition("file_path", file_path)]),
        collection,
    )
    if matched:
        logger.info("Deleted %d chunks for path %s", matched, file_path)
    return matched


def delete_chunks_by_source(
    source: str,
    collection_name: str | None = None,
) -> int:
    """Legacy fallback for points that do not carry a stable path or ID."""
    collection = collection_name or settings.qdrant_collection
    matched = _delete_by_filter(
        Filter(must=[_condition("source", source)]),
        collection,
    )
    if matched:
        logger.info("Deleted %d legacy chunks for source %s", matched, source)
    return matched


def delete_chunks_by_document_id(
    document_id: str,
    collection_name: str | None = None,
) -> int:
    """Delete every version of one registry-backed document."""
    collection = collection_name or settings.qdrant_collection
    matched = _delete_by_filter(
        Filter(must=[_condition("document_id", document_id)]),
        collection,
    )
    if matched:
        logger.info("Deleted %d chunks for document %s", matched, document_id)
    return matched


def delete_chunks_by_document_version(
    document_id: str,
    version_id: str,
    collection_name: str | None = None,
) -> int:
    """Delete one exact document version without touching a replacement."""
    collection = collection_name or settings.qdrant_collection
    matched = _delete_by_filter(
        Filter(
            must=[
                _condition("document_id", document_id),
                _condition("version_id", version_id),
            ]
        ),
        collection,
    )
    if matched:
        logger.info(
            "Deleted %d chunks for document %s version %s",
            matched,
            document_id,
            version_id,
        )
    return matched


def delete_legacy_file_version(
    file_path: str,
    content_md5: str,
    replacement_version_id: str,
    collection_name: str | None = None,
) -> int:
    """Delete pre-registry points after their replacement is safely upserted.

    ``must_not version_id=replacement`` prevents a same-content pipeline
    migration from deleting the new points when old and new metadata share the
    same file path and MD5.
    """
    collection = collection_name or settings.qdrant_collection
    must = [_condition("file_path", file_path)]
    if content_md5:
        must.append(_condition("md5", content_md5))
    matched = _delete_by_filter(
        Filter(
            must=must,
            must_not=[_condition("version_id", replacement_version_id)],
        ),
        collection,
    )
    if matched:
        logger.info("Deleted %d legacy chunks for %s", matched, file_path)
    return matched


def _validate_chunks_and_embeddings(
    chunks: list,
    embeddings: list[list[float]],
) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError(
            "Chunk/embedding count mismatch: "
            f"{len(chunks)} chunks != {len(embeddings)} embeddings"
        )
    if not chunks:
        return

    dimensions = {len(vector) for vector in embeddings}
    if 0 in dimensions or len(dimensions) != 1:
        raise ValueError("Embedding vectors must be non-empty and have equal dimensions")

    required_metadata = {
        "document_id",
        "version_id",
        "chunk_index",
        "source",
        "stored_path",
        "md5",
        "pipeline_fingerprint",
    }
    seen_indices: set[tuple[str, str, int]] = set()
    for chunk in chunks:
        missing = sorted(
            key
            for key in required_metadata
            if chunk.metadata.get(key) in (None, "")
            and key != "chunk_index"
        )
        if chunk.metadata.get("chunk_index") is None:
            missing.append("chunk_index")
        if missing:
            raise ValueError(
                "Chunk metadata is missing fields: " + ", ".join(sorted(set(missing)))
            )
        index = chunk.metadata["chunk_index"]
        if not isinstance(index, int) or index < 0:
            raise ValueError("chunk_index must be a non-negative integer")
        identity = (
            chunk.metadata["document_id"],
            chunk.metadata["version_id"],
            index,
        )
        if identity in seen_indices:
            raise ValueError(f"Duplicate chunk identity: {identity}")
        seen_indices.add(identity)


def _existing_collection_vector_size(
    client: QdrantClient,
    collection_name: str,
) -> int:
    collection = client.get_collection(collection_name=collection_name)
    vectors = collection.config.params.vectors
    if hasattr(vectors, "size"):
        return int(vectors.size)
    if isinstance(vectors, dict) and len(vectors) == 1:
        vector_params = next(iter(vectors.values()))
        if hasattr(vector_params, "size"):
            return int(vector_params.size)
    raise ValueError(
        f"Collection '{collection_name}' uses an unsupported named-vector configuration"
    )


def bulk_upsert_chunks(
    chunks: list,
    embeddings: list[list[float]],
    collection_name: str | None = None,
    upsert_batch_size: int = UPSERT_BATCH_SIZE,
) -> int:
    """Validate and synchronously upsert versioned chunks into Qdrant."""
    _validate_chunks_and_embeddings(chunks, embeddings)
    if not chunks:
        return 0
    if upsert_batch_size <= 0:
        raise ValueError("upsert_batch_size must be greater than zero")

    client = _get_client()
    collection = collection_name or settings.qdrant_collection
    embedding_size = len(embeddings[0])
    if not client.collection_exists(collection_name=collection):
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(
                size=embedding_size,
                distance=Distance.COSINE,
            ),
        )
        logger.info(
            "Created collection '%s' (vector_size=%d)",
            collection,
            embedding_size,
        )
    else:
        collection_size = _existing_collection_vector_size(client, collection)
        if collection_size != embedding_size:
            raise ValueError(
                f"Embedding dimension {embedding_size} does not match collection "
                f"'{collection}' dimension {collection_size}; rebuild the collection "
                "before switching embedding models"
            )

    points = []
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        metadata = dict(chunk.metadata)
        point_id = _make_point_id(
            metadata["document_id"],
            metadata["version_id"],
            metadata["chunk_index"],
        )
        points.append(
            PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "page_content": chunk.page_content,
                    "metadata": metadata,
                },
            )
        )

    total = 0
    for start in range(0, len(points), upsert_batch_size):
        batch = points[start : start + upsert_batch_size]
        client.upsert(
            collection_name=collection,
            points=batch,
            wait=True,
        )
        total += len(batch)

    logger.info("Bulk upserted %d points to collection '%s'", total, collection)
    return total


def _scroll_metadata(
    collection_name: str,
    scroll_filter: Filter | None = None,
) -> list[dict[str, Any]]:
    client = _get_client()
    if not client.collection_exists(collection_name=collection_name):
        return []

    metadata_rows: list[dict[str, Any]] = []
    offset = None
    while True:
        records, offset = client.scroll(
            collection_name=collection_name,
            scroll_filter=scroll_filter,
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for record in records:
            payload = record.payload or {}
            metadata_rows.append(dict(payload.get("metadata") or {}))
        if offset is None:
            break
    return metadata_rows


def find_indexed_documents_by_source(
    source: str,
    collection_name: str | None = None,
) -> list[dict[str, Any]]:
    """Inspect exact-source matches, grouping legacy points by stored path."""
    collection = collection_name or settings.qdrant_collection
    rows = _scroll_metadata(
        collection,
        Filter(must=[_condition("source", source)]),
    )
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for metadata in rows:
        qdrant_document_id = metadata.get("document_id") or ""
        stored_path = (
            metadata.get("stored_path")
            or metadata.get("file_path")
            or ""
        )
        document_id = qdrant_document_id or (
            make_legacy_document_id(collection, stored_path)
            if stored_path
            else ""
        )
        group_key = (
            "document" if qdrant_document_id else "legacy",
            qdrant_document_id or stored_path or source,
        )
        group = groups.setdefault(
            group_key,
            {
                "document_id": document_id or None,
                "legacy": not bool(qdrant_document_id),
                "source": metadata.get("source") or source,
                "stored_path": stored_path or None,
                "file_path": metadata.get("file_path") or stored_path or None,
                "version_id": metadata.get("version_id") or None,
                "md5": metadata.get("md5") or None,
                "chunks": 0,
            },
        )
        group["chunks"] += 1
    return list(groups.values())


def find_indexed_document_by_id(
    document_id: str,
    collection_name: str | None = None,
) -> dict[str, Any] | None:
    """Resolve either a payload ID or a deterministic legacy path ID."""
    collection = collection_name or settings.qdrant_collection
    rows = _scroll_metadata(collection)
    matched: dict[str, Any] | None = None
    for metadata in rows:
        qdrant_document_id = metadata.get("document_id") or ""
        stored_path = (
            metadata.get("stored_path")
            or metadata.get("file_path")
            or ""
        )
        effective_id = qdrant_document_id or (
            make_legacy_document_id(collection, stored_path)
            if stored_path
            else ""
        )
        if effective_id != document_id:
            continue
        if matched is None:
            source = metadata.get("source", "unknown")
            matched = {
                "document_id": effective_id,
                "legacy": not bool(qdrant_document_id),
                "source": source,
                "stored_path": stored_path or None,
                "file_path": metadata.get("file_path") or stored_path or None,
                "file_type": metadata.get("file_type")
                or (
                    f".{source.rsplit('.', 1)[-1].lower()}"
                    if "." in source
                    else "unknown"
                ),
                "chunks": 0,
            }
        matched["chunks"] += 1
    return matched


def list_indexed_documents(
    collection_name: str | None = None,
) -> list[dict[str, Any]]:
    """List current Qdrant documents, preserving document IDs when available."""
    collection = collection_name or settings.qdrant_collection
    rows = _scroll_metadata(collection)
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for metadata in rows:
        source = metadata.get("source", "unknown")
        qdrant_document_id = metadata.get("document_id") or ""
        stored_path = metadata.get("stored_path") or metadata.get("file_path") or ""
        document_id = qdrant_document_id or (
            make_legacy_document_id(collection, stored_path)
            if stored_path
            else ""
        )
        key = (
            "document" if qdrant_document_id else "legacy",
            qdrant_document_id or stored_path or source,
        )
        group = groups.setdefault(
            key,
            {
                "document_id": document_id or None,
                "legacy": not bool(qdrant_document_id),
                "source": source,
                "file_type": metadata.get("file_type")
                or (
                    f".{source.rsplit('.', 1)[-1].lower()}"
                    if "." in source
                    else "unknown"
                ),
                "chunks": 0,
            },
        )
        group["chunks"] += 1

    return sorted(
        groups.values(),
        key=lambda item: (item["source"], item.get("document_id") or ""),
    )

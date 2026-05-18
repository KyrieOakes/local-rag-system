"""
Qdrant 批量写入模块。

提供高性能的 Qdrant 写入和删除操作：
- delete_chunks_by_filepath() — 按 metadata.file_path 精确删除某文件的所有已有分块
  （用于文件变更时的"先删后写"策略）
- bulk_upsert_chunks() — 将预计算好嵌入的分块批量写入 Qdrant
  - 使用 UUID v5 生成确定性点 ID（基于 file_path + md5 + chunk_index）
  - 自动分批（默认 500 点/批），避免超过 Qdrant 的 32MB 单次载荷限制
  - 每个点存储 page_content（文本）和 metadata（来源、文件路径、类型、校验等）

与向量检索模块不同，这里直连 qdrant_client 而非使用 LangChain 封装，
以获得更好的批量写入性能和控制。
"""

import logging
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    Filter,
    FieldCondition,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


def _make_point_id(file_path: str, md5: str, chunk_index: int) -> str:
    namespace = uuid.NAMESPACE_DNS
    return str(uuid.uuid5(namespace, f"{file_path}:{md5}:{chunk_index}"))


def delete_chunks_by_filepath(file_path: str, collection_name: str | None = None) -> int:
    """Delete all chunks whose metadata.file_path matches the given path."""
    client = _get_client()
    collection = collection_name or settings.qdrant_collection

    count_result = client.count(
        collection_name=collection,
        count_filter=Filter(
            must=[
                FieldCondition(
                    key="metadata.file_path",
                    match=MatchValue(value=file_path),
                )
            ]
        ),
        exact=True,
    )
    matched = count_result.count

    if matched == 0:
        return 0

    client.delete(
        collection_name=collection,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="metadata.file_path",
                    match=MatchValue(value=file_path),
                )
            ]
        ),
    )
    logger.info("Deleted %d chunks for %s", matched, file_path)
    return matched


# Qdrant has a 32 MB payload limit per upsert call.
# Each point with its vector and payload is roughly 40–60 KB, so 500 points
# keeps a single batch well under the limit.
UPSERT_BATCH_SIZE = 500


def bulk_upsert_chunks(
    chunks: list,
    embeddings: list[list[float]],
    collection_name: str | None = None,
    upsert_batch_size: int = UPSERT_BATCH_SIZE,
) -> int:
    """Bulk-upsert chunks with pre-computed embeddings into Qdrant.

    Splits points into batches to stay under Qdrant's 32 MB payload limit.

    Each chunk (LangChain Document) must have metadata fields:
    source, file_path, file_name, file_type, chunk_index, md5.
    """
    if not chunks:
        return 0

    client = _get_client()
    collection = collection_name or settings.qdrant_collection

    # ── 集合不存在时自动创建（clear_qdrant 后首次摄入）──
    if not client.collection_exists(collection_name=collection):
        vector_size = len(embeddings[0])
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        logger.info("Created collection '%s' (vector_size=%d)", collection, vector_size)

    points = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        meta = chunk.metadata
        file_path = meta.get("file_path", "")
        file_md5 = meta.get("md5", "")

        point_id = _make_point_id(file_path, file_md5, i)

        points.append(
            PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "page_content": chunk.page_content,
                    "metadata": dict(meta),
                },
            )
        )

    total = 0
    num_batches = (len(points) + upsert_batch_size - 1) // upsert_batch_size
    for batch_idx in range(num_batches):
        start = batch_idx * upsert_batch_size
        end = min(start + upsert_batch_size, len(points))
        batch = points[start:end]

        logger.info("Upsert batch %d/%d (%d points)", batch_idx + 1, num_batches, len(batch))
        client.upsert(collection_name=collection, points=batch)
        total += len(batch)

    logger.info("Bulk upserted %d points to collection '%s' in %d batches",
                total, collection, num_batches)
    return total

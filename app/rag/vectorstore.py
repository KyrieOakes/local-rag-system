from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from langchain_qdrant import QdrantVectorStore

from app.core.config import settings
from app.rag.embeddings import get_embedding_model


def _get_qdrant_client() -> QdrantClient:
    """获取底层 Qdrant 客户端，用于管理操作"""
    return QdrantClient(url=settings.qdrant_url)


# 获取现有的向量数据库实例，如果不存在则创建一个新的实例
def get_vectorstore() -> QdrantVectorStore:
    # 获取嵌入模型实例
    embedding_model = get_embedding_model()

    # 从现有的Qdrant集合中创建一个QdrantVectorStore实例，
    # 使用指定的嵌入模型、集合名称和URL连接到Qdrant数据库
    return QdrantVectorStore.from_existing_collection(
        embedding=embedding_model,
        collection_name=settings.qdrant_collection,
        url=settings.qdrant_url,
    )

# 从文档列表创建一个新的向量数据库实例，并将文档存储到Qdrant数据库中
def create_vectorstore_from_documents(documents):
    embedding_model = get_embedding_model()

    # 从文档列表创建一个新的QdrantVectorStore实例，并将文档存储到指定的Qdrant集合中，
    return QdrantVectorStore.from_documents(
        documents=documents,
        embedding=embedding_model,
        collection_name=settings.qdrant_collection,
        url=settings.qdrant_url,
        # 如果集合已经存在，则不强制重新创建，而是使用现有的集合来存储文档
        force_recreate=False,
    )


def list_all_documents() -> list[dict]:
    """
    列出 Qdrant 中所有不重复的文档（按 source 分组）。
    返回格式: [{"source": "foo.pdf", "file_type": ".pdf", "chunks": 12}, ...]
    """
    client = _get_qdrant_client()

    source_chunk_count: dict[str, int] = {}
    source_file_type: dict[str, str] = {}

    # 使用 scroll 遍历所有点
    offset = None
    while True:
        records, offset = client.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=None,
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        for record in records:
            if record.payload is None:
                continue
            metadata = record.payload.get("metadata", {})
            source = metadata.get("source", "unknown")
            source_chunk_count[source] = source_chunk_count.get(source, 0) + 1

            # 从 source 文件名推断文件类型
            if source not in source_file_type:
                suffix = source.rsplit(".", 1)[-1].lower() if "." in source else "unknown"
                source_file_type[source] = f".{suffix}" if suffix != "unknown" else source

        if offset is None:
            break

    return [
        {
            "source": source,
            "file_type": source_file_type.get(source, "unknown"),
            "chunks": count,
        }
        for source, count in sorted(source_chunk_count.items())
    ]


def delete_document_by_source(source: str) -> int:
    """
    按 source（原始文件名）删除文档的所有分块。
    返回删除的点数。
    """
    client = _get_qdrant_client()

    # 先统计匹配的点数
    count_result = client.count(
        collection_name=settings.qdrant_collection,
        count_filter=Filter(
            must=[
                FieldCondition(
                    key="metadata.source",
                    match=MatchValue(value=source),
                )
            ]
        ),
        exact=True,
    )
    matched_count = count_result.count

    if matched_count == 0:
        return 0

    # 删除匹配的点
    client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="metadata.source",
                    match=MatchValue(value=source),
                )
            ]
        ),
    )

    return matched_count

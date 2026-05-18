"""
文档摄取服务层。

对上传 API 提供单文档摄取封装：
ingest_document() 委托给 ingest_file_paths() 流水线，
通过 source_map 将 UUID 文件名映射回用户上传的原始文件名，
确保 Qdrant 中存储的 source 字段为用户可读的文件名。
"""

from app.rag.ingestion.ingest_pipeline import ingest_file_paths


def ingest_document(file_path: str, original_filename: str) -> dict:
    result = ingest_file_paths(
        file_paths=[file_path],
        collection_name=None,
        batch_size=64,
        source_map={file_path: original_filename},
    )

    return {
        "filename": original_filename,
        "file_path": file_path,
        "chunks": result.get("chunks", 0),
        "status": result.get("status", "error"),
    }

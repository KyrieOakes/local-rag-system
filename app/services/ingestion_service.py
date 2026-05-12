from app.rag.ingestion.ingest_pipeline import ingest_file_paths


# 处理文档的摄取过程，使用统一的 batch-embed + bulk-upsert pipeline
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

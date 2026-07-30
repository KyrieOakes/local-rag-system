"""Upload-facing wrapper around the versioned ingestion pipeline."""

from pathlib import Path

from app.rag.ingestion.ingest_pipeline import ingest_file_paths


def ingest_document(file_path: str, original_filename: str) -> dict:
    source = Path(original_filename.replace("\\", "/")).name
    result = ingest_file_paths(
        file_paths=[file_path],
        collection_name=None,
        batch_size=64,
        source_map={file_path: source},
        origin="upload",
    )
    documents = result.get("documents") or []
    document = documents[0] if documents else {}

    return {
        "filename": source,
        "source": document.get("source", result.get("source", source)),
        "document_id": document.get(
            "document_id",
            result.get("document_id"),
        ),
        "chunks": document.get("chunks", result.get("chunks", 0)),
        "status": document.get("status", result.get("status", "error")),
        "change_type": document.get("change_type"),
        "cleanup_pending": bool(document.get("cleanup_pending", False)),
    }

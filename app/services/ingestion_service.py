"""Upload-facing wrappers around the versioned ingestion pipeline."""

from __future__ import annotations

from app.core.config import settings
from app.rag.ingestion.ingest_pipeline import ingest_file_paths
from app.utils.file_utils import normalize_upload_relative_path


def _public_result(document: dict, fallback_source: str) -> dict:
    if document.get("status") == "error":
        return {
            "filename": fallback_source,
            "source": fallback_source,
            "status": "error",
            "error": "Document ingestion failed",
        }
    return {
        "filename": fallback_source,
        "source": document.get("source", fallback_source),
        "document_id": document.get("document_id"),
        "chunks": document.get("chunks", 0),
        "status": document.get("status", "error"),
        "change_type": document.get("change_type"),
        "cleanup_pending": bool(document.get("cleanup_pending", False)),
    }


def ingest_document(
    file_path: str,
    original_filename: str,
    relative_path: str | None = None,
) -> dict:
    source = normalize_upload_relative_path(
        relative_path,
        original_filename=original_filename,
    )
    result = ingest_file_paths(
        file_paths=[file_path],
        collection_name=None,
        batch_size=settings.embedding_batch_size,
        source_map={file_path: source},
        origin="upload",
    )
    documents = result.get("documents") or []
    document = documents[0] if documents else {}
    if not document:
        document = result
    return _public_result(document, source)


def ingest_documents(files: list[dict[str, str]]) -> list[dict]:
    """Ingest one upload batch with bounded document-level concurrency."""
    if not files:
        return []

    paths: list[str] = []
    source_map: dict[str, str] = {}
    sources: list[str] = []
    for item in files:
        source = normalize_upload_relative_path(
            item.get("relative_path"),
            original_filename=item.get("original_filename"),
        )
        file_path = item["file_path"]
        paths.append(file_path)
        sources.append(source)
        source_map[file_path] = source

    result = ingest_file_paths(
        file_paths=paths,
        collection_name=None,
        batch_size=settings.embedding_batch_size,
        source_map=source_map,
        origin="upload",
        max_workers=settings.upload_ingestion_concurrency,
        continue_on_error=True,
    )
    documents = result.get("documents") or []
    if len(documents) != len(files):
        raise RuntimeError("Ingestion pipeline returned an unexpected result count")
    return [
        _public_result(document, source)
        for document, source in zip(documents, sources, strict=True)
    ]

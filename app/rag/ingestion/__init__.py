"""Public interfaces for versioned document ingestion."""

from app.rag.ingestion.checksum_store import (
    ChecksumStore,
    make_document_id,
    make_legacy_document_id,
)
from app.rag.ingestion.batch_embedder import embed_texts
from app.rag.ingestion.bulk_writer import (
    bulk_upsert_chunks,
    delete_chunks_by_document_id,
    delete_chunks_by_document_version,
    delete_chunks_by_filepath,
)
from app.rag.ingestion.ingest_pipeline import (
    build_pipeline_fingerprint,
    ingest_directory,
    ingest_file_paths,
)

__all__ = [
    "ChecksumStore",
    "make_document_id",
    "make_legacy_document_id",
    "embed_texts",
    "bulk_upsert_chunks",
    "delete_chunks_by_document_id",
    "delete_chunks_by_document_version",
    "delete_chunks_by_filepath",
    "build_pipeline_fingerprint",
    "ingest_directory",
    "ingest_file_paths",
]

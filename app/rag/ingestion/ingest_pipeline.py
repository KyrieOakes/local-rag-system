import hashlib
import logging
import time
from pathlib import Path

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.ingestion.checksum_store import ChecksumStore
from app.rag.ingestion.batch_embedder import embed_texts
from app.rag.ingestion.bulk_writer import bulk_upsert_chunks, delete_chunks_by_filepath
from app.rag.loader import load_document
from app.rag.splitter import split_documents

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf", ".docx"}


def _compute_md5(file_path: Path) -> str:
    md5_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()


def _scan_files(input_dir: str, extensions: set[str] | None = None) -> list[Path]:
    exts = extensions or SUPPORTED_EXTENSIONS
    root = Path(input_dir)
    if not root.exists():
        raise FileNotFoundError(f"Directory not found: {input_dir}")
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {input_dir}")

    files = []
    for ext in exts:
        files.extend(root.rglob(f"*{ext}"))
        files.extend(root.rglob(f"*{ext.upper()}"))

    # deduplicate and sort
    seen = set()
    result = []
    for f in sorted(files):
        if f.is_file() and f not in seen:
            seen.add(f)
            result.append(f)
    return result


def _load_and_split(
    file_paths: list[Path],
    source_map: dict[str, str] | None = None,
) -> list[Document]:
    """Load and split a list of files. Returns chunks with enriched metadata.

    Args:
        file_paths: Absolute paths to load.
        source_map: Optional mapping from file_path (str) to display name for
                    the ``source`` metadata field. When omitted, ``fp.name`` is used.
    """
    all_chunks = []
    for fp in file_paths:
        logger.info("Loading: %s", fp)
        try:
            documents = load_document(str(fp))
        except Exception:
            logger.exception("Failed to load %s", fp)
            continue

        suffix = fp.suffix.lower()
        file_md5 = _compute_md5(fp)
        display_name = (source_map or {}).get(str(fp), fp.name)

        for doc in documents:
            doc.metadata["source"] = display_name
            doc.metadata["file_path"] = str(fp)
            doc.metadata["file_name"] = display_name
            doc.metadata["file_type"] = suffix
            doc.metadata["md5"] = file_md5

        chunks = split_documents(documents)
        logger.info("  -> %d chunks", len(chunks))
        all_chunks.extend(chunks)

    return all_chunks


def ingest_file_paths(
    file_paths: list[str],
    collection_name: str | None = None,
    batch_size: int = 64,
    source_map: dict[str, str] | None = None,
) -> dict:
    """Ingest specific file paths. Used by the upload API.

    Args:
        file_paths: Absolute paths to ingest.
        collection_name: Qdrant collection name (default from settings).
        batch_size: Chunks per embedding API call.
        source_map: Optional mapping from file_path to display name for
                    the ``source`` metadata field. Uploads use this to
                    preserve the user-facing filename.
    """
    if not file_paths:
        return {"status": "no_files", "files_processed": 0, "chunks": 0}

    collection = collection_name or settings.qdrant_collection
    paths = [Path(p) for p in file_paths]
    store = ChecksumStore()

    # Compute MD5s
    new_or_changed = []
    for fp in paths:
        if not fp.exists():
            logger.warning("File not found, skipping: %s", fp)
            continue
        current_md5 = _compute_md5(fp)
        existing = store.get(str(fp))
        if existing and existing["md5"] == current_md5:
            logger.info("Skipping unchanged file: %s", fp.name)
            continue
        if existing:
            logger.info("File changed, re-processing: %s", fp.name)
            delete_chunks_by_filepath(str(fp), collection)
        new_or_changed.append(fp)

    if not new_or_changed:
        return {"status": "up_to_date", "files_processed": 0, "chunks": 0}

    t0 = time.perf_counter()
    chunks = _load_and_split(new_or_changed, source_map=source_map)
    texts = [c.page_content for c in chunks]
    embeddings = embed_texts(texts, batch_size=batch_size)
    points_count = bulk_upsert_chunks(chunks, embeddings, collection)

    # Update checksums (count chunks per file)
    for fp in new_or_changed:
        file_chunk_count = sum(1 for c in chunks if c.metadata.get("file_path") == str(fp))
        store.upsert(str(fp), _compute_md5(fp), file_chunk_count, collection)

    elapsed = time.perf_counter() - t0
    logger.info("Ingested %d files -> %d chunks in %.1fs", len(new_or_changed), points_count, elapsed)
    return {
        "status": "indexed",
        "files_processed": len(new_or_changed),
        "chunks": points_count,
        "elapsed_seconds": round(elapsed, 1),
    }


def ingest_directory(
    input_dir: str,
    collection_name: str | None = None,
    batch_size: int = 64,
) -> dict:
    """Main entry point: recursively scan, load, split, embed, and upsert."""
    t_start = time.perf_counter()
    collection = collection_name or settings.qdrant_collection
    store = ChecksumStore()

    # 1. Scan
    files = _scan_files(input_dir)
    logger.info("Scanned %s: found %d supported files", input_dir, len(files))

    if not files:
        logger.warning("No supported files found in %s", input_dir)
        return {"status": "no_files", "total_files": 0}

    # 2. Classify: new, changed, unchanged
    new_files = []
    changed_files = []
    unchanged_files = []

    for fp in files:
        current_md5 = _compute_md5(fp)
        existing = store.get(str(fp))
        if existing is None:
            new_files.append(fp)
        elif existing["md5"] != current_md5:
            changed_files.append(fp)
        else:
            unchanged_files.append(fp)

    logger.info(
        "Classification: %d new, %d changed, %d unchanged (skipped)",
        len(new_files), len(changed_files), len(unchanged_files),
    )

    # 3. Delete old chunks for changed files
    for fp in changed_files:
        delete_chunks_by_filepath(str(fp), collection)

    # 4. Process new + changed
    files_to_process = new_files + changed_files
    if not files_to_process:
        elapsed = time.perf_counter() - t_start
        logger.info("All files up to date (%.1fs)", elapsed)
        return {
            "status": "up_to_date",
            "total_files": len(files),
            "new_files": 0,
            "changed_files": 0,
            "skipped_files": len(unchanged_files),
            "total_chunks": 0,
            "points_upserted": 0,
            "elapsed_seconds": round(elapsed, 1),
        }

    # 5. Load + split
    t_load = time.perf_counter()
    chunks = _load_and_split(files_to_process)
    logger.info("Total chunks after splitting: %d (load+split took %.1fs)",
                len(chunks), time.perf_counter() - t_load)

    # 6. Batch embed
    texts = [c.page_content for c in chunks]
    embeddings = embed_texts(texts, batch_size=batch_size)

    # 7. Bulk upsert
    points_count = bulk_upsert_chunks(chunks, embeddings, collection)

    # 8. Update checksums
    for fp in files_to_process:
        file_chunk_count = sum(1 for c in chunks if c.metadata.get("file_path") == str(fp))
        store.upsert(str(fp), _compute_md5(fp), file_chunk_count, collection)

    elapsed = time.perf_counter() - t_start
    logger.info(
        "Ingest complete: %d files -> %d chunks in %.1fs",
        len(files_to_process), points_count, elapsed,
    )

    return {
        "status": "indexed",
        "total_files": len(files),
        "new_files": len(new_files),
        "changed_files": len(changed_files),
        "skipped_files": len(unchanged_files),
        "total_chunks": len(chunks),
        "points_upserted": points_count,
        "elapsed_seconds": round(elapsed, 1),
    }

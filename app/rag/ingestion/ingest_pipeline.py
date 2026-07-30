"""Transactional-ish document ingestion with versioned Qdrant points.

Each logical document has a stable ``document_id``.  A content hash plus a
pipeline fingerprint produces a ``version_id``.  New points are fully embedded
and synchronously upserted before the previous version is removed, so a failed
load/embed/upsert leaves the active index and SQLite state untouched.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.ingestion.batch_embedder import embed_texts
from app.rag.ingestion.bulk_writer import (
    bulk_upsert_chunks,
    delete_chunks_by_document_id,
    delete_chunks_by_document_version,
    delete_legacy_file_version,
    find_indexed_documents_by_source,
)
from app.rag.ingestion.checksum_store import (
    ChecksumStore,
    make_document_id,
    make_legacy_document_id,
)
from app.rag.loader import load_document
from app.rag.splitter import split_documents

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf", ".docx"}
SPLITTER_VERSION = "markdown-h1-h3-recursive-v1"
UPLOAD_ROOT = Path("data/raw")
_ingestion_lock = threading.RLock()


def _compute_md5(file_path: Path) -> str:
    md5_hash = hashlib.md5()
    with file_path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()


def _canonical_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_within(path: Path, root: Path) -> bool:
    try:
        _canonical_path(path).relative_to(_canonical_path(root))
        return True
    except ValueError:
        return False


def build_pipeline_fingerprint(collection_name: str) -> str:
    """Hash every setting that can change vector or chunk semantics."""
    payload = {
        "collection_name": collection_name,
        "embedding": {
            "base_url": settings.embedding_base_url.rstrip("/"),
            "model": settings.embedding_model,
            "revision": settings.embedding_revision,
        },
        "chunking": {
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "splitter_version": SPLITTER_VERSION,
        },
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _make_version_id(
    document_id: str,
    content_md5: str,
    pipeline_fingerprint: str,
) -> str:
    raw = f"{document_id}\0{content_md5}\0{pipeline_fingerprint}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _identity_key(
    stored_path: Path,
    source: str,
    origin: str,
) -> str:
    if origin == "upload":
        normalized_source = unicodedata.normalize("NFC", source)
        return f"upload:{normalized_source}"
    return f"directory:{_canonical_path(stored_path)}"


def _metadata_file_path(stored_path: Path) -> str:
    """Preserve the repo-relative file_path contract used by evaluations."""
    canonical = _canonical_path(stored_path)
    try:
        return str(canonical.relative_to(_canonical_path(Path.cwd())))
    except ValueError:
        return str(canonical)


def _scan_files(
    input_dir: str,
    extensions: set[str] | None = None,
) -> list[Path]:
    exts = {extension.lower() for extension in (extensions or SUPPORTED_EXTENSIONS)}
    root = Path(input_dir)
    if not root.exists():
        raise FileNotFoundError(f"Directory not found: {input_dir}")
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {input_dir}")

    canonical_root = _canonical_path(root)
    result: list[Path] = []
    seen: set[Path] = set()
    for candidate in sorted(root.rglob("*")):
        if (
            candidate.is_file()
            and candidate.suffix.lower() in exts
            and _is_within(candidate, canonical_root)
        ):
            canonical = _canonical_path(candidate)
            if canonical not in seen:
                seen.add(canonical)
                result.append(canonical)
    return result


def _load_and_split_file(
    file_path: Path,
    *,
    source: str,
    document_id: str,
    version_id: str,
    pipeline_fingerprint: str,
    content_md5: str,
) -> list[Document]:
    """Load one file and attach stable per-file chunk metadata."""
    documents = load_document(str(file_path))
    if not documents:
        raise ValueError(f"Document loader returned no content: {file_path}")

    base_metadata = {
        "document_id": document_id,
        "version_id": version_id,
        "source": source,
        "original_source": source,
        "stored_path": str(file_path),
        # Keep file_path for retrieval/evaluation compatibility.
        "file_path": _metadata_file_path(file_path),
        "file_name": source,
        "file_type": file_path.suffix.lower(),
        "md5": content_md5,
        "pipeline_fingerprint": pipeline_fingerprint,
    }
    for document in documents:
        document.metadata.update(base_metadata)

    chunks = split_documents(documents)
    if not chunks:
        raise ValueError(f"Document splitter returned no chunks: {file_path}")
    for chunk_index, chunk in enumerate(chunks):
        chunk.metadata.update(base_metadata)
        chunk.metadata["chunk_index"] = chunk_index
    return chunks


def _load_and_split(
    file_paths: list[Path],
    source_map: dict[str, str] | None = None,
) -> list[Document]:
    """Compatibility helper that now guarantees per-file chunk indexes."""
    collection = settings.qdrant_collection
    fingerprint = build_pipeline_fingerprint(collection)
    all_chunks: list[Document] = []
    for raw_path in file_paths:
        canonical = _canonical_path(raw_path)
        source = _source_for_path(raw_path, canonical, source_map)
        content_md5 = _compute_md5(canonical)
        identity_key = _identity_key(canonical, source, "directory")
        document_id = make_document_id(collection, identity_key)
        version_id = _make_version_id(document_id, content_md5, fingerprint)
        all_chunks.extend(
            _load_and_split_file(
                canonical,
                source=source,
                document_id=document_id,
                version_id=version_id,
                pipeline_fingerprint=fingerprint,
                content_md5=content_md5,
            )
        )
    return all_chunks


def _source_for_path(
    raw_path: Path,
    canonical_path: Path,
    source_map: dict[str, str] | None,
) -> str:
    source_map = source_map or {}
    source = (
        source_map.get(str(raw_path))
        or source_map.get(str(canonical_path))
        or raw_path.name
    )
    source = Path(str(source)).name
    if not source:
        raise ValueError(f"Unable to determine original filename for {raw_path}")
    return source


def _safe_unlink_upload(path: str | Path) -> bool:
    candidate = Path(path)
    if not _is_within(candidate, UPLOAD_ROOT):
        logger.warning("Refusing to unlink non-upload path: %s", candidate)
        return False
    if not candidate.exists():
        return False
    if not candidate.is_file():
        logger.warning("Refusing to unlink non-file upload path: %s", candidate)
        return False
    candidate.unlink()
    return True


def _looks_like_legacy_upload(path: str | Path) -> bool:
    candidate = Path(path)
    stem = candidate.stem
    return (
        _is_within(candidate, UPLOAD_ROOT)
        and len(stem) == 32
        and all(character in "0123456789abcdefABCDEF" for character in stem)
    )


def _legacy_upload_predecessors(
    source: str,
    collection_name: str,
    active_document_id: str,
    store: ChecksumStore,
) -> list[dict[str, Any]]:
    """Map pre-registry UUID uploads onto the new original-name identity."""
    predecessors: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for match in find_indexed_documents_by_source(source, collection_name):
        if not match.get("legacy"):
            continue
        stored_path = match.get("stored_path") or match.get("file_path")
        if (
            not stored_path
            or stored_path in seen_paths
            or not _looks_like_legacy_upload(stored_path)
        ):
            continue
        seen_paths.add(stored_path)
        registered = store.get(stored_path, collection_name)
        if (
            registered is not None
            and registered.get("document_id") != active_document_id
        ):
            predecessors.append(registered)
            continue
        predecessors.append(
            {
                "document_id": make_legacy_document_id(
                    collection_name,
                    stored_path,
                ),
                "collection_name": collection_name,
                "source": match.get("source") or source,
                "stored_path": stored_path,
                "content_md5": match.get("md5") or "",
                "version_id": "",
                "origin": "legacy",
            }
        )
    return predecessors


def _rollback_new_version(
    document_id: str,
    version_id: str,
    collection_name: str,
) -> None:
    try:
        delete_chunks_by_document_version(
            document_id,
            version_id,
            collection_name,
        )
    except Exception:
        logger.exception(
            "Failed to roll back document %s version %s",
            document_id,
            version_id,
        )


def _delete_previous_version(
    previous: dict[str, Any],
    replacement_version_id: str,
    collection_name: str,
) -> int:
    if previous.get("version_id"):
        return delete_chunks_by_document_version(
            previous["document_id"],
            previous["version_id"],
            collection_name,
        )
    return delete_legacy_file_version(
        previous["stored_path"],
        previous.get("content_md5") or previous.get("md5") or "",
        replacement_version_id,
        collection_name,
    )


def _retry_pending_cleanups(
    store: ChecksumStore,
    collection_name: str,
    document_id: str | None = None,
) -> int:
    """Retry durable old-version cleanup records.

    The active registry row already points at the new version.  A cleanup
    failure therefore leaves both versions available and the queue row intact;
    it must never trigger rollback of the active version.
    """
    failures = 0
    for cleanup in store.list_pending_cleanups(collection_name, document_id):
        try:
            previous_version_id = cleanup.get("previous_version_id") or ""
            if previous_version_id:
                delete_chunks_by_document_version(
                    cleanup.get("previous_document_id")
                    or cleanup["active_document_id"],
                    previous_version_id,
                    collection_name,
                )
            else:
                delete_legacy_file_version(
                    cleanup["previous_stored_path"],
                    cleanup.get("previous_content_md5") or "",
                    cleanup["active_version_id"],
                    collection_name,
                )

            previous_origin = cleanup.get("previous_origin") or "legacy"
            if previous_origin == "upload" or (
                previous_origin == "legacy"
                and _looks_like_legacy_upload(cleanup["previous_stored_path"])
            ):
                _safe_unlink_upload(cleanup["previous_stored_path"])

            store.complete_pending_cleanup(cleanup["cleanup_id"])
        except Exception:
            failures += 1
            logger.exception(
                "Deferred cleanup remains pending for document %s",
                cleanup.get("active_document_id"),
            )
    return failures


def _has_pending_cleanup(
    store: ChecksumStore,
    collection_name: str,
    document_id: str,
) -> bool:
    return len(store.list_pending_cleanups(collection_name, document_id)) > 0


def _ingest_one(
    raw_path: Path,
    *,
    collection_name: str,
    batch_size: int,
    source: str,
    origin: str,
    scan_root: str,
    store: ChecksumStore,
) -> dict[str, Any]:
    canonical_path = _canonical_path(raw_path)
    if not canonical_path.exists() or not canonical_path.is_file():
        raise FileNotFoundError(f"File not found: {raw_path}")

    identity_key = _identity_key(canonical_path, source, origin)
    document_id = make_document_id(collection_name, identity_key)
    content_md5 = _compute_md5(canonical_path)
    fingerprint = build_pipeline_fingerprint(collection_name)
    version_id = _make_version_id(document_id, content_md5, fingerprint)
    previous = store.get_by_document_id(document_id, collection_name)
    _retry_pending_cleanups(
        store,
        collection_name,
        document_id,
    )
    legacy_predecessors = (
        _legacy_upload_predecessors(
            source,
            collection_name,
            document_id,
            store,
        )
        if origin == "upload"
        else []
    )

    if (
        previous
        and previous["content_md5"] == content_md5
        and previous["pipeline_fingerprint"] == fingerprint
        and previous["version_id"] == version_id
    ):
        if legacy_predecessors:
            store.activate_document(previous, legacy_predecessors)
            _retry_pending_cleanups(
                store,
                collection_name,
                document_id,
            )
        if origin == "upload" and previous["stored_path"] != str(canonical_path):
            _safe_unlink_upload(canonical_path)
        return {
            "status": "up_to_date",
            "change_type": "unchanged",
            "document_id": document_id,
            "source": source,
            "stored_path": previous["stored_path"],
            "chunks": 0,
            "cleanup_pending": _has_pending_cleanup(
                store,
                collection_name,
                document_id,
            ),
        }

    change_type = "changed" if previous else "new"
    chunks = _load_and_split_file(
        canonical_path,
        source=source,
        document_id=document_id,
        version_id=version_id,
        pipeline_fingerprint=fingerprint,
        content_md5=content_md5,
    )
    embeddings = embed_texts(
        [chunk.page_content for chunk in chunks],
        batch_size=batch_size,
    )
    if len(chunks) != len(embeddings):
        raise ValueError(
            "Embedding service returned an unexpected number of vectors: "
            f"{len(embeddings)} for {len(chunks)} chunks"
        )

    try:
        points_count = bulk_upsert_chunks(
            chunks,
            embeddings,
            collection_name,
        )
    except Exception:
        _rollback_new_version(document_id, version_id, collection_name)
        raise
    if points_count != len(chunks):
        _rollback_new_version(document_id, version_id, collection_name)
        raise ValueError(
            f"Qdrant acknowledged {points_count} points for {len(chunks)} chunks"
        )

    record = {
        "document_id": document_id,
        "collection_name": collection_name,
        "identity_key": identity_key,
        "source": source,
        "stored_path": str(canonical_path),
        "content_md5": content_md5,
        "pipeline_fingerprint": fingerprint,
        "version_id": version_id,
        "chunk_count": points_count,
        "origin": origin,
        "scan_root": scan_root,
    }
    predecessors = ([previous] if previous else []) + legacy_predecessors
    try:
        store.activate_document(record, predecessors)
    except Exception:
        _rollback_new_version(document_id, version_id, collection_name)
        raise

    _retry_pending_cleanups(
        store,
        collection_name,
        document_id,
    )

    return {
        "status": "indexed",
        "change_type": change_type,
        "document_id": document_id,
        "source": source,
        "stored_path": str(canonical_path),
        "chunks": points_count,
        "cleanup_pending": _has_pending_cleanup(
            store,
            collection_name,
            document_id,
        ),
    }


def ingest_file_paths(
    file_paths: list[str],
    collection_name: str | None = None,
    batch_size: int = 64,
    source_map: dict[str, str] | None = None,
    *,
    origin: str = "file",
    scan_root: str | None = None,
) -> dict[str, Any]:
    """Ingest explicit paths and return backward-compatible aggregate fields."""
    if not file_paths:
        return {"status": "no_files", "files_processed": 0, "chunks": 0}
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    collection = collection_name or settings.qdrant_collection
    store = ChecksumStore()
    results: list[dict[str, Any]] = []
    normalized_origin = "upload" if origin == "upload" else "directory"
    normalized_root = (
        str(_canonical_path(Path(scan_root)))
        if scan_root
        else ""
    )

    with _ingestion_lock:
        _retry_pending_cleanups(store, collection)
        for path_text in file_paths:
            raw_path = Path(path_text)
            canonical = _canonical_path(raw_path)
            source = _source_for_path(raw_path, canonical, source_map)
            results.append(
                _ingest_one(
                    raw_path,
                    collection_name=collection,
                    batch_size=batch_size,
                    source=source,
                    origin=normalized_origin,
                    scan_root=normalized_root,
                    store=store,
                )
            )

    indexed = [result for result in results if result["status"] == "indexed"]
    aggregate_status = "indexed" if indexed else "up_to_date"
    response: dict[str, Any] = {
        "status": aggregate_status,
        "files_processed": len(indexed),
        "chunks": sum(result["chunks"] for result in indexed),
        "documents": results,
    }
    if len(results) == 1:
        response.update(
            {
                "document_id": results[0]["document_id"],
                "source": results[0]["source"],
                "stored_path": results[0]["stored_path"],
            }
        )
    return response


def _reconcile_removed_files(
    *,
    scan_root: Path,
    collection_name: str,
    scanned_paths: set[str],
    store: ChecksumStore,
) -> tuple[int, list[dict[str, str]]]:
    removed = 0
    failures: list[dict[str, str]] = []
    canonical_root = _canonical_path(scan_root)
    for record in store.list_for_scan_root(str(canonical_root), collection_name):
        stored_path = record["stored_path"]
        if stored_path in scanned_paths:
            continue
        if not _is_within(Path(stored_path), canonical_root):
            logger.error(
                "Refusing out-of-root cleanup for registered path %s",
                stored_path,
            )
            failures.append(
                {
                    "file_path": stored_path,
                    "error": "registered path is outside scan root",
                }
            )
            continue
        try:
            delete_chunks_by_document_id(
                record["document_id"],
                collection_name,
            )
            store.delete_document(record["document_id"], collection_name)
            removed += 1
            logger.info("Removed stale indexed document: %s", stored_path)
        except Exception as error:
            logger.exception("Failed to remove stale document %s", stored_path)
            failures.append(
                {"file_path": stored_path, "error": str(error)}
            )
    return removed, failures


def ingest_directory(
    input_dir: str,
    collection_name: str | None = None,
    batch_size: int = 64,
) -> dict[str, Any]:
    """Ingest a directory and safely reconcile files removed from that root."""
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    started = time.perf_counter()
    collection = collection_name or settings.qdrant_collection
    root = _canonical_path(Path(input_dir))
    files = _scan_files(str(root))
    scanned_paths = {str(path) for path in files}
    store = ChecksumStore()

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    with _ingestion_lock:
        _retry_pending_cleanups(store, collection)
        for file_path in files:
            try:
                results.append(
                    _ingest_one(
                        file_path,
                        collection_name=collection,
                        batch_size=batch_size,
                        source=file_path.name,
                        origin="directory",
                        scan_root=str(root),
                        store=store,
                    )
                )
            except Exception as error:
                logger.exception("Failed to ingest %s", file_path)
                failures.append(
                    {"file_path": str(file_path), "error": str(error)}
                )

        removed_files, removal_failures = _reconcile_removed_files(
            scan_root=root,
            collection_name=collection,
            scanned_paths=scanned_paths,
            store=store,
        )
        failures.extend(removal_failures)

    new_files = sum(
        result["change_type"] == "new" and result["status"] == "indexed"
        for result in results
    )
    changed_files = sum(
        result["change_type"] == "changed" and result["status"] == "indexed"
        for result in results
    )
    skipped_files = sum(result["status"] == "up_to_date" for result in results)
    chunks = sum(result["chunks"] for result in results)

    if failures:
        status = "partial"
    elif new_files or changed_files or removed_files:
        status = "indexed"
    elif files:
        status = "up_to_date"
    else:
        status = "no_files"

    elapsed = time.perf_counter() - started
    return {
        "status": status,
        "total_files": len(files),
        "new_files": new_files,
        "changed_files": changed_files,
        "skipped_files": skipped_files,
        "removed_files": removed_files,
        "failed_files": len(failures),
        "failures": failures,
        "total_chunks": chunks,
        "points_upserted": chunks,
        "elapsed_seconds": round(elapsed, 1),
    }

"""Document listing and exact lifecycle deletion."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.config import settings
from app.rag.ingestion.bulk_writer import (
    delete_chunks_by_document_id,
    delete_chunks_by_filepath,
    delete_chunks_by_source,
    find_indexed_document_by_id,
    find_indexed_documents_by_source,
    list_indexed_documents,
)
from app.rag.ingestion.checksum_store import ChecksumStore
from app.utils.file_utils import remove_upload_file


def list_documents() -> list[dict]:
    """List indexed logical documents, including stable IDs for new records."""
    documents = list_indexed_documents(settings.qdrant_collection)
    return [
        {key: value for key, value in document.items() if key != "legacy"}
        for document in documents
    ]


def _looks_like_document_id(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (TypeError, ValueError, AttributeError):
        return False


def _ambiguous_result(source: str, candidates: list[dict[str, Any]]) -> dict:
    return {
        "source": source,
        "deleted_chunks": 0,
        "file_deleted": False,
        "status": "ambiguous",
        "candidates": [
            {
                "document_id": candidate.get("document_id"),
                "source": candidate.get("source"),
            }
            for candidate in candidates
        ],
    }


def _delete_registered_document(
    record: dict[str, Any],
    store: ChecksumStore,
) -> dict:
    collection = record["collection_name"]
    pending_cleanups = store.list_pending_cleanups(
        collection,
        record["document_id"],
    )
    if record.get("version_id"):
        deleted_chunks = delete_chunks_by_document_id(
            record["document_id"],
            collection,
        )
    else:
        # Migrated legacy Qdrant payloads have no document_id/version_id.
        deleted_chunks = delete_chunks_by_filepath(
            record["stored_path"],
            collection,
        )

    for cleanup in pending_cleanups:
        previous_document_id = cleanup.get("previous_document_id")
        previous_version_id = cleanup.get("previous_version_id")
        previous_stored_path = cleanup.get("previous_stored_path")
        if previous_version_id and previous_document_id != record["document_id"]:
            deleted_chunks += delete_chunks_by_document_id(
                previous_document_id,
                collection,
            )
        elif not previous_version_id and previous_stored_path:
            deleted_chunks += delete_chunks_by_filepath(
                previous_stored_path,
                collection,
            )
        remove_upload_file(previous_stored_path)

    file_deleted = remove_upload_file(record["stored_path"])
    state_deleted = store.delete_document(record["document_id"], collection)
    return {
        "document_id": record["document_id"],
        "source": record["source"],
        "deleted_chunks": deleted_chunks,
        "file_deleted": file_deleted,
        "state_deleted": state_deleted,
        "status": "deleted",
    }


def delete_document(identifier: str) -> dict:
    """Delete by stable document ID, or by an unambiguous legacy source.

    Source-based compatibility never guesses among multiple same-name paths.
    New clients should pass the ``document_id`` returned by the listing API.
    """
    collection = settings.qdrant_collection
    store = ChecksumStore()

    registered = store.get_by_document_id(identifier, collection)
    if registered is not None:
        return _delete_registered_document(registered, store)

    indexed_by_id = (
        find_indexed_document_by_id(identifier, collection)
        if _looks_like_document_id(identifier)
        else None
    )
    if indexed_by_id is not None:
        stored_path = (
            indexed_by_id.get("stored_path")
            or indexed_by_id.get("file_path")
        )
        if indexed_by_id.get("legacy") and stored_path:
            deleted_chunks = delete_chunks_by_filepath(stored_path, collection)
            store.delete(stored_path, collection)
            state_deleted = True
        else:
            deleted_chunks = delete_chunks_by_document_id(identifier, collection)
            state_deleted = store.delete_document(identifier, collection)
        return {
            "document_id": identifier,
            "source": indexed_by_id.get("source"),
            "deleted_chunks": deleted_chunks,
            "file_deleted": remove_upload_file(stored_path),
            "state_deleted": state_deleted,
            "status": "deleted",
        }

    source_matches = store.find_by_source(identifier, collection)
    if len(source_matches) > 1:
        return _ambiguous_result(identifier, source_matches)
    if len(source_matches) == 1:
        indexed_matches = find_indexed_documents_by_source(identifier, collection)
        foreign_matches = [
            match
            for match in indexed_matches
            if match.get("document_id") != source_matches[0]["document_id"]
        ]
        if foreign_matches:
            return _ambiguous_result(
                identifier,
                source_matches + foreign_matches,
            )
        return _delete_registered_document(source_matches[0], store)

    # Backward compatibility for indexes created before document_registry.
    indexed_matches = find_indexed_documents_by_source(identifier, collection)
    if len(indexed_matches) > 1:
        return _ambiguous_result(identifier, indexed_matches)
    if not indexed_matches:
        return {
            "source": identifier,
            "deleted_chunks": 0,
            "file_deleted": False,
            "status": "not_found",
        }

    match = indexed_matches[0]
    document_id = match.get("document_id")
    stored_path = match.get("stored_path") or match.get("file_path")
    if match.get("legacy") and stored_path:
        deleted_chunks = delete_chunks_by_filepath(stored_path, collection)
        store.delete(stored_path, collection)
        state_deleted = True
    elif document_id:
        deleted_chunks = delete_chunks_by_document_id(document_id, collection)
        state_deleted = store.delete_document(document_id, collection)
    elif stored_path:
        deleted_chunks = delete_chunks_by_filepath(stored_path, collection)
        store.delete(stored_path, collection)
        state_deleted = True
    else:
        # Very old points may only have source metadata.  The single grouped
        # match above makes this fallback unambiguous.
        deleted_chunks = delete_chunks_by_source(identifier, collection)
        state_deleted = False

    file_deleted = remove_upload_file(stored_path)
    return {
        "document_id": document_id,
        "source": identifier,
        "deleted_chunks": deleted_chunks,
        "file_deleted": file_deleted,
        "state_deleted": state_deleted,
        "status": "deleted",
    }

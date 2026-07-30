"""SQLite-backed ingestion state and document registry.

The original project stored only ``file_path`` and ``md5`` in
``file_checksums``.  That is not enough for UUID-named uploads, pipeline
configuration changes, or safe document deletion.  ``document_registry`` is
the authoritative state table now; the legacy table is retained and updated
for backward compatibility.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings

DB_PATH = Path("data/ingestion_state.db")
DOCUMENT_ID_NAMESPACE = uuid.UUID("28d84791-6b99-4e3b-8cf0-24cc80eb3ad7")


def make_document_id(collection_name: str, identity_key: str) -> str:
    """Return a stable ID for one logical document inside a collection."""
    return str(
        uuid.uuid5(
            DOCUMENT_ID_NAMESPACE,
            f"{collection_name}\0{identity_key}",
        )
    )


def make_legacy_document_id(collection_name: str, stored_path: str) -> str:
    """Return the stable path-based ID used for pre-registry Qdrant points."""
    return make_document_id(collection_name, _legacy_identity(stored_path))


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    timeout_seconds = settings.sqlite_busy_timeout_ms / 1000
    conn = sqlite3.connect(str(DB_PATH), timeout=timeout_seconds)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}")
    conn.row_factory = sqlite3.Row
    return conn


def _legacy_identity(file_path: str) -> str:
    canonical = str(Path(file_path).expanduser().resolve(strict=False))
    return f"directory:{canonical}"


def _registry_record(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    # Compatibility aliases used by older callers and DevLog-era code.
    record["file_path"] = record["stored_path"]
    record["md5"] = record["content_md5"]
    return record


def _sync_legacy_checksum(
    conn: sqlite3.Connection,
    stored_path: str,
) -> None:
    """Mirror one remaining registry row into the path-only legacy table."""
    remaining = conn.execute(
        """
        SELECT stored_path, content_md5, last_ingested_at, chunk_count,
               collection_name
        FROM document_registry
        WHERE stored_path = ?
        ORDER BY last_ingested_at DESC
        LIMIT 1
        """,
        (stored_path,),
    ).fetchone()
    if remaining is None:
        conn.execute(
            "DELETE FROM file_checksums WHERE file_path = ?",
            (stored_path,),
        )
        return
    conn.execute(
        """
        INSERT INTO file_checksums (
            file_path, md5, last_ingested_at, chunk_count, collection_name
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            md5 = excluded.md5,
            last_ingested_at = excluded.last_ingested_at,
            chunk_count = excluded.chunk_count,
            collection_name = excluded.collection_name
        """,
        (
            remaining["stored_path"],
            remaining["content_md5"],
            remaining["last_ingested_at"],
            remaining["chunk_count"],
            remaining["collection_name"],
        ),
    )


def init_db() -> None:
    """Create the registry and migrate legacy checksum rows in place."""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS file_checksums (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                md5 TEXT NOT NULL,
                last_ingested_at TEXT NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                collection_name TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_registry (
                document_id TEXT NOT NULL,
                collection_name TEXT NOT NULL,
                identity_key TEXT NOT NULL,
                source TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                content_md5 TEXT NOT NULL,
                pipeline_fingerprint TEXT NOT NULL DEFAULT '',
                version_id TEXT NOT NULL DEFAULT '',
                chunk_count INTEGER NOT NULL DEFAULT 0,
                origin TEXT NOT NULL DEFAULT 'legacy',
                scan_root TEXT NOT NULL DEFAULT '',
                last_ingested_at TEXT NOT NULL,
                PRIMARY KEY (document_id, collection_name)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_cleanup_queue (
                cleanup_id INTEGER PRIMARY KEY AUTOINCREMENT,
                active_document_id TEXT NOT NULL,
                active_version_id TEXT NOT NULL,
                collection_name TEXT NOT NULL,
                previous_document_id TEXT NOT NULL DEFAULT '',
                previous_version_id TEXT NOT NULL DEFAULT '',
                previous_stored_path TEXT NOT NULL,
                previous_content_md5 TEXT NOT NULL DEFAULT '',
                previous_origin TEXT NOT NULL DEFAULT 'legacy',
                previous_source TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE (
                    active_document_id,
                    collection_name,
                    previous_document_id,
                    previous_version_id,
                    previous_stored_path
                )
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_file_path ON file_checksums(file_path)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_registry_stored_path "
            "ON document_registry(stored_path, collection_name)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_registry_source "
            "ON document_registry(source, collection_name)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_registry_scan_root "
            "ON document_registry(scan_root, collection_name)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cleanup_active "
            "ON document_cleanup_queue(active_document_id, collection_name)"
        )

        # Migration is idempotent.  A legacy point has no version_id in Qdrant,
        # so the empty string intentionally tells cleanup code to use the
        # legacy file_path/md5 filter after the new version is upserted.
        legacy_rows = conn.execute(
            """
            SELECT file_path, md5, last_ingested_at, chunk_count, collection_name
            FROM file_checksums
            """
        ).fetchall()
        for row in legacy_rows:
            represented = conn.execute(
                """
                SELECT 1 FROM document_registry
                WHERE stored_path = ? AND collection_name = ?
                LIMIT 1
                """,
                (row["file_path"], row["collection_name"]),
            ).fetchone()
            if represented is not None:
                continue
            identity_key = _legacy_identity(row["file_path"])
            document_id = make_legacy_document_id(
                row["collection_name"],
                row["file_path"],
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO document_registry (
                    document_id, collection_name, identity_key, source,
                    stored_path, content_md5, pipeline_fingerprint, version_id,
                    chunk_count, origin, scan_root, last_ingested_at
                )
                VALUES (?, ?, ?, ?, ?, ?, '', '', ?, 'legacy', '', ?)
                """,
                (
                    document_id,
                    row["collection_name"],
                    identity_key,
                    Path(row["file_path"]).name,
                    row["file_path"],
                    row["md5"],
                    row["chunk_count"],
                    row["last_ingested_at"],
                ),
            )


class ChecksumStore:
    """Compatibility facade over the authoritative document registry."""

    def __init__(self) -> None:
        init_db()

    def get(
        self,
        file_path: str,
        collection_name: str | None = None,
    ) -> Optional[dict[str, Any]]:
        clauses = ["stored_path = ?"]
        params: list[Any] = [file_path]
        if collection_name is not None:
            clauses.append("collection_name = ?")
            params.append(collection_name)

        with _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM document_registry WHERE "
                + " AND ".join(clauses)
                + " ORDER BY last_ingested_at DESC LIMIT 1",
                params,
            ).fetchone()
        return _registry_record(row) if row is not None else None

    def get_by_document_id(
        self,
        document_id: str,
        collection_name: str,
    ) -> Optional[dict[str, Any]]:
        with _get_conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM document_registry
                WHERE document_id = ? AND collection_name = ?
                """,
                (document_id, collection_name),
            ).fetchone()
        return _registry_record(row) if row is not None else None

    def find_by_source(
        self,
        source: str,
        collection_name: str,
    ) -> list[dict[str, Any]]:
        with _get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM document_registry
                WHERE source = ? AND collection_name = ?
                ORDER BY last_ingested_at DESC
                """,
                (source, collection_name),
            ).fetchall()
        return [_registry_record(row) for row in rows]

    def list_for_scan_root(
        self,
        scan_root: str,
        collection_name: str,
    ) -> list[dict[str, Any]]:
        with _get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM document_registry
                WHERE scan_root = ? AND collection_name = ? AND origin = 'directory'
                ORDER BY stored_path
                """,
                (scan_root, collection_name),
            ).fetchall()
        return [_registry_record(row) for row in rows]

    @staticmethod
    def _validate_document_record(record: dict[str, Any]) -> None:
        required = {
            "document_id",
            "collection_name",
            "identity_key",
            "source",
            "stored_path",
            "content_md5",
            "pipeline_fingerprint",
            "version_id",
            "chunk_count",
            "origin",
            "scan_root",
        }
        missing = sorted(required - record.keys())
        if missing:
            raise ValueError(
                "Document registry record is missing fields: " + ", ".join(missing)
            )

    @staticmethod
    def _upsert_document_row(
        conn: sqlite3.Connection,
        record: dict[str, Any],
        timestamp: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO document_registry (
                document_id, collection_name, identity_key, source,
                stored_path, content_md5, pipeline_fingerprint, version_id,
                chunk_count, origin, scan_root, last_ingested_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id, collection_name) DO UPDATE SET
                identity_key = excluded.identity_key,
                source = excluded.source,
                stored_path = excluded.stored_path,
                content_md5 = excluded.content_md5,
                pipeline_fingerprint = excluded.pipeline_fingerprint,
                version_id = excluded.version_id,
                chunk_count = excluded.chunk_count,
                origin = excluded.origin,
                scan_root = excluded.scan_root,
                last_ingested_at = excluded.last_ingested_at
            """,
            (
                record["document_id"],
                record["collection_name"],
                record["identity_key"],
                record["source"],
                record["stored_path"],
                record["content_md5"],
                record["pipeline_fingerprint"],
                record["version_id"],
                record["chunk_count"],
                record["origin"],
                record["scan_root"],
                timestamp,
            ),
        )

    def activate_document(
        self,
        record: dict[str, Any],
        previous_records: list[dict[str, Any]] | None = None,
    ) -> None:
        """Atomically activate a version and persist every required cleanup.

        Qdrant cleanup happens only after this transaction commits.  Therefore a
        registry failure can safely roll back the newly written Qdrant version,
        while a later cleanup failure leaves a durable, idempotent retry record.
        """
        self._validate_document_record(record)
        timestamp = record.get(
            "last_ingested_at",
            time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        previous_records = previous_records or []
        with _get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                """
                SELECT stored_path FROM document_registry
                WHERE document_id = ? AND collection_name = ?
                """,
                (record["document_id"], record["collection_name"]),
            ).fetchone()
            self._upsert_document_row(conn, record, timestamp)
            conn.execute(
                """
                UPDATE document_cleanup_queue
                SET active_version_id = ?
                WHERE active_document_id = ? AND collection_name = ?
                """,
                (
                    record["version_id"],
                    record["document_id"],
                    record["collection_name"],
                ),
            )

            paths_to_sync = {record["stored_path"]}
            if previous is not None:
                paths_to_sync.add(previous["stored_path"])

            for cleanup in previous_records:
                previous_document_id = cleanup.get("document_id") or ""
                previous_version_id = cleanup.get("version_id") or ""
                previous_stored_path = cleanup.get("stored_path") or cleanup.get(
                    "file_path"
                )
                if not previous_stored_path:
                    raise ValueError("Previous cleanup record is missing stored_path")
                if (
                    previous_document_id == record["document_id"]
                    and previous_version_id == record["version_id"]
                ):
                    continue

                conn.execute(
                    """
                    INSERT OR IGNORE INTO document_cleanup_queue (
                        active_document_id, active_version_id, collection_name,
                        previous_document_id, previous_version_id,
                        previous_stored_path, previous_content_md5,
                        previous_origin, previous_source, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["document_id"],
                        record["version_id"],
                        record["collection_name"],
                        previous_document_id,
                        previous_version_id,
                        previous_stored_path,
                        cleanup.get("content_md5") or cleanup.get("md5") or "",
                        cleanup.get("origin") or "legacy",
                        cleanup.get("source") or "",
                        timestamp,
                    ),
                )
                paths_to_sync.add(previous_stored_path)

                if (
                    previous_document_id
                    and previous_document_id != record["document_id"]
                ):
                    conn.execute(
                        """
                        DELETE FROM document_registry
                        WHERE document_id = ? AND collection_name = ?
                        """,
                        (previous_document_id, record["collection_name"]),
                    )

            for stored_path in paths_to_sync:
                _sync_legacy_checksum(conn, stored_path)

    def upsert_document(self, record: dict[str, Any]) -> None:
        self.activate_document(record)

    def list_pending_cleanups(
        self,
        collection_name: str,
        document_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["collection_name = ?"]
        params: list[Any] = [collection_name]
        if document_id is not None:
            clauses.append("active_document_id = ?")
            params.append(document_id)
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM document_cleanup_queue WHERE "
                + " AND ".join(clauses)
                + " ORDER BY cleanup_id",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def complete_pending_cleanup(self, cleanup_id: int) -> bool:
        with _get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "DELETE FROM document_cleanup_queue WHERE cleanup_id = ?",
                (cleanup_id,),
            )
        return cursor.rowcount > 0

    def upsert(
        self,
        file_path: str,
        md5: str,
        chunk_count: int,
        collection_name: str,
        **metadata: Any,
    ) -> None:
        """Backward-compatible checksum upsert used by older callers."""
        identity_key = metadata.get("identity_key") or _legacy_identity(file_path)
        self.upsert_document(
            {
                "document_id": metadata.get("document_id")
                or make_document_id(collection_name, identity_key),
                "collection_name": collection_name,
                "identity_key": identity_key,
                "source": metadata.get("source") or Path(file_path).name,
                "stored_path": metadata.get("stored_path") or file_path,
                "content_md5": md5,
                "pipeline_fingerprint": metadata.get("pipeline_fingerprint", ""),
                "version_id": metadata.get("version_id", ""),
                "chunk_count": chunk_count,
                "origin": metadata.get("origin", "legacy"),
                "scan_root": metadata.get("scan_root", ""),
            }
        )

    def delete_document(
        self,
        document_id: str,
        collection_name: str,
    ) -> bool:
        with _get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT stored_path FROM document_registry
                WHERE document_id = ? AND collection_name = ?
                """,
                (document_id, collection_name),
            ).fetchall()
            cursor = conn.execute(
                """
                DELETE FROM document_registry
                WHERE document_id = ? AND collection_name = ?
                """,
                (document_id, collection_name),
            )
            conn.execute(
                """
                DELETE FROM document_cleanup_queue
                WHERE collection_name = ?
                  AND (
                    active_document_id = ?
                    OR previous_document_id = ?
                  )
                """,
                (collection_name, document_id, document_id),
            )
            for row in rows:
                _sync_legacy_checksum(conn, row["stored_path"])
        return cursor.rowcount > 0

    def delete(
        self,
        file_path: str,
        collection_name: str | None = None,
    ) -> None:
        clauses = ["stored_path = ?"]
        params: list[Any] = [file_path]
        if collection_name is not None:
            clauses.append("collection_name = ?")
            params.append(collection_name)
        with _get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM document_registry WHERE " + " AND ".join(clauses),
                params,
            )
            cleanup_clauses = ["previous_stored_path = ?"]
            cleanup_params: list[Any] = [file_path]
            if collection_name is not None:
                cleanup_clauses.append("collection_name = ?")
                cleanup_params.append(collection_name)
            conn.execute(
                "DELETE FROM document_cleanup_queue WHERE "
                + " AND ".join(cleanup_clauses),
                cleanup_params,
            )
            _sync_legacy_checksum(conn, file_path)

    def delete_paths(
        self,
        stored_paths: list[str],
        collection_name: str | None = None,
    ) -> None:
        for stored_path in dict.fromkeys(stored_paths):
            self.delete(stored_path, collection_name)

    def all(self) -> dict[str, dict[str, Any]]:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM document_registry ORDER BY stored_path"
            ).fetchall()
        return {
            row["stored_path"]: _registry_record(row)
            for row in rows
        }

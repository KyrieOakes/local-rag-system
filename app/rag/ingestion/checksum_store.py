import sqlite3
import time
from pathlib import Path
from typing import Optional

DB_PATH = Path("data/ingestion_state.db")


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    conn = _get_conn()
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
        "CREATE INDEX IF NOT EXISTS idx_file_path ON file_checksums(file_path)"
    )
    conn.commit()
    conn.close()


class ChecksumStore:
    def __init__(self) -> None:
        init_db()

    def get(self, file_path: str) -> Optional[dict]:
        conn = _get_conn()
        row = conn.execute(
            "SELECT file_path, md5, last_ingested_at, chunk_count, collection_name "
            "FROM file_checksums WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return {
            "file_path": row[0],
            "md5": row[1],
            "last_ingested_at": row[2],
            "chunk_count": row[3],
            "collection_name": row[4],
        }

    def upsert(self, file_path: str, md5: str, chunk_count: int, collection_name: str) -> None:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO file_checksums (file_path, md5, last_ingested_at, chunk_count, collection_name) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(file_path) DO UPDATE SET "
            "md5 = excluded.md5, last_ingested_at = excluded.last_ingested_at, "
            "chunk_count = excluded.chunk_count, collection_name = excluded.collection_name",
            (file_path, md5, time.strftime("%Y-%m-%dT%H:%M:%S"), chunk_count, collection_name),
        )
        conn.commit()
        conn.close()

    def delete(self, file_path: str) -> None:
        conn = _get_conn()
        conn.execute("DELETE FROM file_checksums WHERE file_path = ?", (file_path,))
        conn.commit()
        conn.close()

    def all(self) -> dict[str, dict]:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT file_path, md5, last_ingested_at, chunk_count, collection_name "
            "FROM file_checksums"
        ).fetchall()
        conn.close()
        return {
            row[0]: {
                "file_path": row[0],
                "md5": row[1],
                "last_ingested_at": row[2],
                "chunk_count": row[3],
                "collection_name": row[4],
            }
            for row in rows
        }

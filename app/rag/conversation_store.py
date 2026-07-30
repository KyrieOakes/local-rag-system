"""
Conversation Store — SQLite-based persistence for chat conversations.

Stores conversation metadata + messages for the sidebar history feature.
Follows the same singleton + context-manager pattern as checksum_store.py.

Tables:
  conversations: id | title | created_at | updated_at
  messages:      id | conversation_id | role | content | sources | routing | created_at

Thread-safe via SQLite WAL mode (enabled at connect time).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

DB_PATH = Path("data/conversations.db")
CONVERSATION_WRITE_LOCKS = 64

# ── Schema ──────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT '',
    summary_through_message_id INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id  TEXT NOT NULL,
    role             TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content          TEXT NOT NULL DEFAULT '',
    sources          TEXT,       -- JSON array or NULL
    routing          TEXT,       -- 'rag' | 'direct' | 'greeting' | NULL
    turn_id          TEXT,       -- optional idempotency key for one Q&A pair
    created_at       REAL NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conv_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created  ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at);
"""


# ── Public API ──────────────────────────────────────────────────────

class ConversationStore:
    """Thread-safe SQLite store for chat conversations."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        busy_timeout_ms: int | None = None,
    ):
        self._db_path = db_path
        self._busy_timeout_ms = (
            settings.sqlite_busy_timeout_ms
            if busy_timeout_ms is None
            else busy_timeout_ms
        )
        if self._busy_timeout_ms < 1:
            raise ValueError("busy_timeout_ms must be at least 1")
        self._lock = threading.Lock()
        self._conversation_write_locks = [
            threading.Lock() for _ in range(CONVERSATION_WRITE_LOCKS)
        ]
        self._initialized = False
        self._init_db()

    # ── init ────────────────────────────────────────────────────────

    def _init_db(self):
        """Create tables and enable WAL mode."""
        db_path_str = str(self._db_path)
        with self._lock:
            conn = sqlite3.connect(
                db_path_str,
                timeout=self._busy_timeout_ms / 1000,
            )
            try:
                conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.executescript(SCHEMA_SQL)
                conversation_columns = {
                    row[1]
                    for row in conn.execute("PRAGMA table_info(conversations)").fetchall()
                }
                if "summary" not in conversation_columns:
                    conn.execute(
                        "ALTER TABLE conversations "
                        "ADD COLUMN summary TEXT NOT NULL DEFAULT ''"
                    )
                if "summary_through_message_id" not in conversation_columns:
                    conn.execute(
                        "ALTER TABLE conversations "
                        "ADD COLUMN summary_through_message_id INTEGER NOT NULL DEFAULT 0"
                    )
                message_columns = {
                    row[1]
                    for row in conn.execute("PRAGMA table_info(messages)").fetchall()
                }
                if "turn_id" not in message_columns:
                    conn.execute("ALTER TABLE messages ADD COLUMN turn_id TEXT")
                conn.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_turn_role
                    ON messages(conversation_id, turn_id, role)
                    WHERE turn_id IS NOT NULL
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_messages_conversation_order
                    ON messages(conversation_id, id)
                    """
                )
                conn.commit()
                self._initialized = True
            finally:
                conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a new connection (WAL mode allows concurrent reads)."""
        conn = sqlite3.connect(
            str(self._db_path),
            timeout=self._busy_timeout_ms / 1000,
        )
        conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _conversation_lock(self, conversation_id: str) -> threading.Lock:
        """Return a bounded striped lock for writes to one conversation."""
        index = hash(conversation_id) % len(self._conversation_write_locks)
        return self._conversation_write_locks[index]

    # ── conversation CRUD ───────────────────────────────────────────

    def list_conversations(self) -> list[dict]:
        """Return all conversations ordered by most-recently-updated, with message counts."""
        if not self._initialized:
            raise RuntimeError("Conversation store is not initialized")
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT c.id, c.title, c.created_at, c.updated_at,
                       COUNT(m.id) AS message_count
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                GROUP BY c.id
                ORDER BY c.updated_at DESC
            """).fetchall()
            return [dict(r) for r in rows]

    def get_conversation(self, conversation_id: str) -> dict | None:
        """Return a conversation with all its messages, or None if not found."""
        if not self._initialized:
            raise RuntimeError("Conversation store is not initialized")
        with self._get_conn() as conn:
            conv = conn.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if not conv:
                return None

            msgs = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
                (conversation_id,),
            ).fetchall()

            result = dict(conv)
            result["messages"] = [
                {
                    "role": m["role"],
                    "content": m["content"],
                    "sources": json.loads(m["sources"]) if m["sources"] else None,
                    "routing": m["routing"],
                    "created_at": m["created_at"],
                }
                for m in msgs
            ]
            return result

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and its messages. Returns True if deleted."""
        if not self._initialized:
            raise RuntimeError("Conversation store is not initialized")
        with self._conversation_lock(conversation_id):
            with self._get_conn() as conn:
                cur = conn.execute(
                    "DELETE FROM conversations WHERE id = ?",
                    (conversation_id,),
                )
                conn.commit()
                deleted = cur.rowcount > 0
                if deleted:
                    logger.info("Deleted conversation %s", conversation_id)
                return deleted

    # ── message helpers ─────────────────────────────────────────────

    def get_context_state(self, conversation_id: str) -> dict | None:
        """Return rolling summary and only messages not covered by that summary."""
        if not self._initialized:
            return None
        with self._get_conn() as conn:
            conversation = conn.execute(
                """
                SELECT summary, summary_through_message_id
                FROM conversations
                WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()
            if not conversation:
                return None

            messages = conn.execute(
                """
                SELECT id, role, content
                FROM messages
                WHERE conversation_id = ? AND id > ?
                ORDER BY id ASC
                """,
                (
                    conversation_id,
                    conversation["summary_through_message_id"],
                ),
            ).fetchall()
            return {
                "summary": conversation["summary"],
                "summary_through_message_id": conversation[
                    "summary_through_message_id"
                ],
                "messages": [dict(message) for message in messages],
            }

    def update_context_summary(
        self,
        conversation_id: str,
        summary: str,
        through_message_id: int,
    ) -> bool:
        """Atomically advance the rolling-summary cursor, rejecting stale writers."""
        with self._conversation_lock(conversation_id):
            with self._get_conn() as conn:
                cursor = conn.execute(
                    """
                    UPDATE conversations
                    SET summary = ?, summary_through_message_id = ?
                    WHERE id = ? AND summary_through_message_id < ?
                    """,
                    (
                        summary,
                        through_message_id,
                        conversation_id,
                        through_message_id,
                    ),
                )
                conn.commit()
                return cursor.rowcount > 0

    def save_exchange(
        self,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        sources: list | None = None,
        routing: str | None = None,
        turn_id: str | None = None,
    ) -> bool:
        """
        Save a complete Q&A exchange (user message + assistant reply).

        Creates the conversation on first call; appends messages on subsequent calls.
        The title is set from the first user message (first 60 chars).
        ``turn_id`` is an optional idempotency key. Repeating a completed turn
        with the same ID is a no-op, while legacy callers without a turn ID
        retain the original append-only behavior. Returns True on success.
        """
        if not self._initialized:
            self._init_db()
        now = time.time()
        title = user_message[:60] + ("..." if len(user_message) > 60 else "")
        sources_json = json.dumps(sources, ensure_ascii=False) if sources else None

        try:
            with self._conversation_lock(conversation_id):
                conn = self._get_conn()
                try:
                    conn.execute("BEGIN IMMEDIATE")

                    if turn_id is not None:
                        existing_count = conn.execute(
                            """
                            SELECT COUNT(*)
                            FROM messages
                            WHERE conversation_id = ? AND turn_id = ?
                            """,
                            (conversation_id, turn_id),
                        ).fetchone()[0]
                        if existing_count >= 2:
                            conn.rollback()
                            logger.debug(
                                "Skipped duplicate turn %s for conversation %s",
                                turn_id,
                                conversation_id,
                            )
                            return True

                    # Upsert conversation: create if new, update timestamp if exists
                    conn.execute("""
                        INSERT INTO conversations (id, title, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            updated_at = excluded.updated_at
                    """, (conversation_id, title, now, now))

                    insert_prefix = "INSERT OR IGNORE" if turn_id is not None else "INSERT"

                    # Insert user message
                    conn.execute(f"""
                        {insert_prefix} INTO messages (
                            conversation_id, role, content, sources, routing,
                            turn_id, created_at
                        )
                        VALUES (?, 'user', ?, NULL, NULL, ?, ?)
                    """, (conversation_id, user_message, turn_id, now))

                    # Insert assistant message
                    conn.execute(f"""
                        {insert_prefix} INTO messages (
                            conversation_id, role, content, sources, routing,
                            turn_id, created_at
                        )
                        VALUES (?, 'assistant', ?, ?, ?, ?, ?)
                    """, (
                        conversation_id,
                        assistant_message,
                        sources_json,
                        routing,
                        turn_id,
                        now,
                    ))

                    if turn_id is not None:
                        saved_count = conn.execute(
                            """
                            SELECT COUNT(*)
                            FROM messages
                            WHERE conversation_id = ? AND turn_id = ?
                            """,
                            (conversation_id, turn_id),
                        ).fetchone()[0]
                        if saved_count != 2:
                            raise sqlite3.IntegrityError(
                                f"incomplete exchange for turn_id={turn_id}"
                            )

                    conn.commit()
                    logger.debug("Saved exchange for conversation %s", conversation_id)
                    return True
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()
        except Exception as exc:
            logger.warning("Failed to save exchange for %s: %s", conversation_id, exc)
            return False


# ── Module-level singleton ──────────────────────────────────────────

_store: ConversationStore | None = None
_store_lock = threading.Lock()


def get_conversation_store() -> ConversationStore:
    """Return the module-level singleton ConversationStore."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ConversationStore()
    return _store

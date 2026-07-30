"""会话历史列表、详情与删除 API 测试。"""

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.rag import conversation_store
from app.rag.conversation_store import ConversationStore


class ConversationsApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @patch("app.api.conversations.get_conversation_store")
    def test_list_conversations_returns_summaries(self, get_store_mock):
        store = MagicMock()
        store.list_conversations.return_value = [
            {
                "id": "c1",
                "title": "RAG design",
                "created_at": 100.0,
                "updated_at": 200.0,
                "message_count": 4,
            }
        ]
        get_store_mock.return_value = store

        response = self.client.get("/conversations")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["id"], "c1")
        self.assertEqual(response.json()[0]["message_count"], 4)
        store.list_conversations.assert_called_once_with()

    @patch("app.api.conversations.get_conversation_store")
    def test_list_conversations_returns_empty_list(self, get_store_mock):
        store = MagicMock()
        store.list_conversations.return_value = []
        get_store_mock.return_value = store

        response = self.client.get("/conversations")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    @patch("app.api.conversations.get_conversation_store")
    def test_list_conversations_maps_store_error_to_500(self, get_store_mock):
        get_store_mock.side_effect = RuntimeError("database locked")

        response = self.client.get("/conversations")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["detail"],
            "Failed to list conversations.",
        )
        self.assertNotIn("database locked", response.text)

    @patch("app.api.conversations.get_conversation_store")
    def test_get_conversation_returns_messages(self, get_store_mock):
        store = MagicMock()
        store.get_conversation.return_value = {
            "id": "c1",
            "title": "RAG design",
            "created_at": 100.0,
            "updated_at": 200.0,
            "messages": [
                {
                    "role": "assistant",
                    "content": "An answer",
                    "sources": [],
                    "routing": "rag",
                    "created_at": 150.0,
                }
            ],
        }
        get_store_mock.return_value = store

        response = self.client.get("/conversations/c1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["messages"][0]["routing"], "rag")
        store.get_conversation.assert_called_once_with("c1")

    @patch("app.api.conversations.get_conversation_store")
    def test_get_conversation_returns_404_when_missing(self, get_store_mock):
        store = MagicMock()
        store.get_conversation.return_value = None
        get_store_mock.return_value = store

        response = self.client.get("/conversations/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Conversation not found")

    @patch("app.api.conversations.get_conversation_store")
    def test_get_conversation_maps_store_error_to_500(self, get_store_mock):
        store = MagicMock()
        store.get_conversation.side_effect = RuntimeError("read failed")
        get_store_mock.return_value = store

        response = self.client.get("/conversations/c1")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["detail"],
            "Failed to get conversation.",
        )
        self.assertNotIn("read failed", response.text)

    @patch("app.api.conversations.get_conversation_store")
    def test_delete_conversation_returns_deleted_id(self, get_store_mock):
        store = MagicMock()
        store.delete_conversation.return_value = True
        get_store_mock.return_value = store

        response = self.client.delete("/conversations/c1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "deleted": "c1"})
        store.delete_conversation.assert_called_once_with("c1")

    @patch("app.api.conversations.get_conversation_store")
    def test_delete_conversation_returns_404_when_missing(self, get_store_mock):
        store = MagicMock()
        store.delete_conversation.return_value = False
        get_store_mock.return_value = store

        response = self.client.delete("/conversations/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Conversation not found")

    @patch("app.api.conversations.get_conversation_store")
    def test_delete_conversation_maps_store_error_to_500(self, get_store_mock):
        store = MagicMock()
        store.delete_conversation.side_effect = RuntimeError("delete failed")
        get_store_mock.return_value = store

        response = self.client.delete("/conversations/c1")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["detail"],
            "Failed to delete conversation.",
        )
        self.assertNotIn("delete failed", response.text)


class ConversationStoreReliabilityTest(unittest.TestCase):
    def test_connections_apply_busy_timeout(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(
                conversation_store.settings,
                "sqlite_busy_timeout_ms",
                1_234,
            ):
                store = ConversationStore(Path(tmp_dir) / "conversations.db")
                with store._get_conn() as connection:
                    busy_timeout = connection.execute(
                        "PRAGMA busy_timeout"
                    ).fetchone()[0]

            self.assertEqual(busy_timeout, 1_234)

    def test_crud_database_errors_are_not_misreported_as_empty_or_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conversations.db")
            operations = [
                store.list_conversations,
                lambda: store.get_conversation("c1"),
                lambda: store.delete_conversation("c1"),
            ]

            for operation in operations:
                with self.subTest(operation=operation):
                    with patch.object(
                        store,
                        "_get_conn",
                        side_effect=sqlite3.OperationalError("database locked"),
                    ):
                        with self.assertRaises(sqlite3.OperationalError):
                            operation()

    def test_turn_id_makes_exchange_save_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conversations.db")

            self.assertTrue(
                store.save_exchange(
                    "c1",
                    "question",
                    "answer",
                    routing="rag",
                    turn_id="turn-1",
                )
            )
            self.assertTrue(
                store.save_exchange(
                    "c1",
                    "question",
                    "answer",
                    routing="rag",
                    turn_id="turn-1",
                )
            )

            conversation = store.get_conversation("c1")
            self.assertEqual(len(conversation["messages"]), 2)

    def test_concurrent_duplicate_turn_is_saved_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conversations.db")

            def save_duplicate(_index: int) -> bool:
                return store.save_exchange(
                    "c1",
                    "question",
                    "answer",
                    routing="rag",
                    turn_id="same-turn",
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(save_duplicate, range(16)))

            self.assertTrue(all(results))
            conversation = store.get_conversation("c1")
            self.assertEqual(
                [message["role"] for message in conversation["messages"]],
                ["user", "assistant"],
            )

    def test_messages_use_id_order_when_timestamps_are_equal(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conversations.db")
            with patch("app.rag.conversation_store.time.time", return_value=100.0):
                store.save_exchange("c1", "question one", "answer one")
                store.save_exchange("c1", "question two", "answer two")

            conversation = store.get_conversation("c1")
            self.assertEqual(
                [message["content"] for message in conversation["messages"]],
                ["question one", "answer one", "question two", "answer two"],
            )

    def test_legacy_messages_table_is_migrated_with_turn_id(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Path(tmp_dir) / "legacy.db"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    """
                    CREATE TABLE conversations (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL DEFAULT '',
                        sources TEXT,
                        routing TEXT,
                        created_at REAL NOT NULL
                    )
                    """
                )
                connection.commit()

            store = ConversationStore(database)
            with store._get_conn() as connection:
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(messages)"
                    ).fetchall()
                }

            self.assertIn("turn_id", columns)


if __name__ == "__main__":
    unittest.main()

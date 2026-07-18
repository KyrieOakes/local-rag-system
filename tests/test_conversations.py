"""会话历史列表、详情与删除 API 测试。"""

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app


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
        self.assertIn("Failed to list conversations", response.json()["detail"])

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
        self.assertIn("Failed to get conversation", response.json()["detail"])

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
        self.assertIn("Failed to delete conversation", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()

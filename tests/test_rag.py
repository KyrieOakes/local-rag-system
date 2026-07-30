"""RAG 同步查询与 SSE 流式 API 测试。"""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.rag.context_manager import ContextWindowExceededError
from app.schemas.rag import QueryResponse, SourceChunk


def _rag_response(question: str = "What is RAG?") -> QueryResponse:
    return QueryResponse(
        question=question,
        answer="Retrieval-augmented generation.",
        sources=[
            SourceChunk(
                content="RAG combines retrieval and generation.",
                source="rag.md",
                file_name="rag.md",
                file_path="docs/rag.md",
                chunk_index=2,
                score=0.91,
            )
        ],
        conversation_id="conversation-1",
        routing="rag",
    )


class RagApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @patch("app.api.rag.query_rag")
    def test_query_returns_structured_response(self, query_rag_mock):
        query_rag_mock.return_value = _rag_response()

        response = self.client.post(
            "/rag/query",
            json={
                "question": "What is RAG?",
                "conversation_id": "conversation-1",
                "history": [{"role": "user", "content": "Earlier question"}],
                "force_rag": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["routing"], "rag")
        self.assertEqual(body["conversation_id"], "conversation-1")
        self.assertEqual(body["sources"][0]["file_path"], "docs/rag.md")
        query_rag_mock.assert_called_once()
        kwargs = query_rag_mock.call_args.kwargs
        self.assertEqual(kwargs["question"], "What is RAG?")
        self.assertEqual(kwargs["conversation_id"], "conversation-1")
        self.assertTrue(kwargs["force_rag"])
        self.assertEqual(kwargs["history"][0].role, "user")

    @patch("app.api.rag.query_rag")
    def test_query_uses_request_defaults(self, query_rag_mock):
        query_rag_mock.return_value = _rag_response("hello")

        response = self.client.post("/rag/query", json={"question": "hello"})

        self.assertEqual(response.status_code, 200)
        kwargs = query_rag_mock.call_args.kwargs
        self.assertIsNone(kwargs["conversation_id"])
        self.assertEqual(kwargs["history"], [])
        self.assertFalse(kwargs["force_rag"])
        self.assertEqual(kwargs["top_k"], 5)

    def test_query_rejects_empty_question(self):
        response = self.client.post("/rag/query", json={"question": ""})

        self.assertEqual(response.status_code, 422)

    def test_query_rejects_invalid_history_role(self):
        response = self.client.post(
            "/rag/query",
            json={
                "question": "continue",
                "history": [{"role": "system", "content": "not allowed"}],
            },
        )

        self.assertEqual(response.status_code, 422)

    @patch("app.api.rag.query_rag")
    def test_query_maps_service_error_to_500(self, query_rag_mock):
        query_rag_mock.side_effect = RuntimeError("vector store unavailable")

        response = self.client.post("/rag/query", json={"question": "test"})

        self.assertEqual(response.status_code, 500)
        self.assertIn("RAG query failed", response.json()["detail"])

    @patch("app.api.rag.query_rag")
    def test_query_maps_context_overflow_to_413(self, query_rag_mock):
        query_rag_mock.side_effect = ContextWindowExceededError("question too large")

        response = self.client.post("/rag/query", json={"question": "test"})

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"], "question too large")

    @patch("app.api.rag.query_rag_stream")
    def test_stream_returns_sse_events(self, query_rag_stream_mock):
        async def fake_stream(**_kwargs):
            yield 'event: routing\ndata: {"routing":"rag","conversation_id":"c1"}\n\n'
            yield 'event: token\ndata: "Answer"\n\n'
            yield 'event: sources\ndata: []\n\n'
            yield "event: done\ndata: {}\n\n"

        query_rag_stream_mock.side_effect = fake_stream

        response = self.client.post(
            "/rag/query/stream",
            json={"question": "stream it", "force_rag": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(response.headers["cache-control"], "no-cache")
        self.assertIn("event: routing", response.text)
        self.assertIn("event: token", response.text)
        self.assertIn("event: done", response.text)
        kwargs = query_rag_stream_mock.call_args.kwargs
        self.assertEqual(kwargs["question"], "stream it")
        self.assertTrue(kwargs["force_rag"])

    def test_stream_rejects_missing_question(self):
        response = self.client.post("/rag/query/stream", json={})

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()

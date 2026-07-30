"""RAG 同步查询与 SSE 流式 API 测试。"""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.documents import Document

from app.api import rag as rag_api
from app.main import app
from app.rag.context_manager import ContextWindowExceededError
from app.schemas.rag import QueryResponse, SourceChunk
from app.services import rag_service


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


def _parse_sse_events(chunks: list[str]) -> list[tuple[str, object]]:
    events = []
    for chunk in chunks:
        lines = chunk.strip().splitlines()
        event_name = lines[0].split(":", 1)[1].strip()
        payload = json.loads(lines[1].split(":", 1)[1].strip())
        events.append((event_name, payload))
    return events


async def _collect_stream(**kwargs) -> list[str]:
    return [chunk async for chunk in rag_service.query_rag_stream(**kwargs)]


class RagApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @patch("app.api.rag.query_rag")
    def test_query_returns_structured_response(self, query_rag_mock):
        query_rag_mock.return_value = _rag_response()

        response = self.client.post(
            "/rag/query",
            headers={"X-Request-ID": "turn-structured-1"},
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
        self.assertEqual(kwargs["turn_id"], "turn-structured-1")

    @patch("app.api.rag.query_rag")
    def test_query_uses_request_defaults(self, query_rag_mock):
        query_rag_mock.return_value = _rag_response("hello")

        with patch.object(rag_api.settings, "top_k", 7):
            response = self.client.post("/rag/query", json={"question": "hello"})

        self.assertEqual(response.status_code, 200)
        kwargs = query_rag_mock.call_args.kwargs
        self.assertIsNone(kwargs["conversation_id"])
        self.assertEqual(kwargs["history"], [])
        self.assertFalse(kwargs["force_rag"])
        self.assertEqual(kwargs["top_k"], 7)

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

    def test_query_rejects_unsafe_conversation_id(self):
        response = self.client.post(
            "/rag/query",
            json={
                "question": "continue",
                "conversation_id": "../another-file",
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_query_rejects_oversized_history_list(self):
        response = self.client.post(
            "/rag/query",
            json={
                "question": "continue",
                "history": [
                    {"role": "user", "content": f"message-{index}"}
                    for index in range(101)
                ],
            },
        )

        self.assertEqual(response.status_code, 422)

    @patch("app.api.rag.query_rag")
    def test_query_maps_service_error_to_500(self, query_rag_mock):
        query_rag_mock.side_effect = RuntimeError("vector store unavailable")

        response = self.client.post("/rag/query", json={"question": "test"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "RAG query failed.")
        self.assertNotIn("vector store unavailable", response.text)

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

        with patch.object(rag_api.settings, "top_k", 9):
            response = self.client.post(
                "/rag/query/stream",
                headers={"X-Request-ID": "turn-stream-1"},
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
        self.assertEqual(kwargs["top_k"], 9)
        self.assertEqual(kwargs["turn_id"], "turn-stream-1")

    def test_stream_rejects_missing_question(self):
        response = self.client.post("/rag/query/stream", json={})

        self.assertEqual(response.status_code, 422)


class RagServiceTopKTest(unittest.TestCase):
    def test_sync_rerank_uses_configured_candidate_and_final_sizes(self):
        routing_memory = SimpleNamespace(messages=[], summary="")
        processed = {
            "needs_rag": True,
            "intent": "question_answering",
            "rewritten_query": "rewritten",
            "direct_answer": None,
        }
        retrieved = [
            (Document(page_content=f"document-{index}", metadata={}), 0.9 - index / 10)
            for index in range(6)
        ]
        reranked = retrieved[:2]
        context_plan = SimpleNamespace(
            documents=[document for document, _score in reranked],
            history=[],
            summary="",
            included_document_count=2,
        )
        with (
            patch(
                "app.services.rag_service.resolve_conversation_memory",
                return_value=object(),
            ),
            patch(
                "app.services.rag_service.prepare_routing_memory",
                return_value=routing_memory,
            ),
            patch("app.services.rag_service.process_query", return_value=processed),
            patch(
                "app.services.rag_service.retrieve_relevant_documents",
                return_value=retrieved,
            ) as retrieval_mock,
            patch(
                "app.services.rag_service._rerank_results",
                return_value=reranked,
            ) as rerank_mock,
            patch(
                "app.services.rag_service.prepare_generation_context",
                return_value=context_plan,
            ),
            patch(
                "app.services.rag_service.generate_answer",
                return_value="answer",
            ),
            patch(
                "app.services.rag_service._schedule_completed_query"
            ) as schedule_mock,
            patch.object(rag_service.settings, "reranker_type", "cross_encoder"),
            patch.object(rag_service.settings, "reranker_candidate_top_n", 11),
            patch.object(rag_service.settings, "reranker_final_top_k", 2),
        ):
            response = rag_service.query_rag(
                question="full pipeline",
                top_k=7,
                conversation_id="c1",
            )

        self.assertEqual(response.answer, "answer")
        self.assertEqual(retrieval_mock.call_args.kwargs["top_k"], 11)
        self.assertEqual(rerank_mock.call_args.args[2], 2)
        self.assertEqual(schedule_mock.call_args.kwargs["top_k"], 2)


class RagStreamReliabilityTest(unittest.IsolatedAsyncioTestCase):
    async def test_direct_response_chunks_preserve_unicode_and_whitespace(self):
        routing_memory = SimpleNamespace(messages=[], summary="")
        answer = "第一行没有空格，应该分块。\n\n  Second   line."
        processed = {
            "needs_rag": False,
            "intent": "chitchat",
            "rewritten_query": None,
            "direct_answer": answer,
        }
        with (
            patch(
                "app.services.rag_service.resolve_conversation_memory",
                return_value=object(),
            ),
            patch(
                "app.services.rag_service.prepare_routing_memory",
                return_value=routing_memory,
            ),
            patch("app.services.rag_service.process_query", return_value=processed),
            patch("app.services.rag_service._schedule_completed_query"),
        ):
            chunks = await _collect_stream(
                question="直接回答",
                conversation_id="c1",
            )

        events = _parse_sse_events(chunks)
        reconstructed = "".join(
            payload for name, payload in events if name == "token"
        )
        self.assertEqual(reconstructed, answer)
        self.assertGreater(
            len([name for name, _payload in events if name == "token"]),
            1,
        )

    async def test_routing_failure_emits_generic_error_then_done(self):
        routing_memory = SimpleNamespace(messages=[], summary="")
        with (
            patch(
                "app.services.rag_service.resolve_conversation_memory",
                return_value=object(),
            ),
            patch(
                "app.services.rag_service.prepare_routing_memory",
                return_value=routing_memory,
            ),
            patch(
                "app.services.rag_service.process_query",
                side_effect=RuntimeError("secret http://internal-model:1234"),
            ),
        ):
            chunks = await _collect_stream(
                question="route this",
                conversation_id="c1",
            )

        events = _parse_sse_events(chunks)
        self.assertEqual([name for name, _data in events], ["error", "done"])
        self.assertEqual(events[0][1]["phase"], "routing")
        self.assertEqual(events[0][1]["message"], "Unable to route the request.")
        self.assertNotIn("internal-model", json.dumps(events))

    async def test_retrieval_failure_emits_error_then_done(self):
        routing_memory = SimpleNamespace(messages=[], summary="")
        processed = {
            "needs_rag": True,
            "intent": "question_answering",
            "rewritten_query": "rewritten",
            "direct_answer": None,
        }
        with (
            patch(
                "app.services.rag_service.resolve_conversation_memory",
                return_value=object(),
            ),
            patch(
                "app.services.rag_service.prepare_routing_memory",
                return_value=routing_memory,
            ),
            patch("app.services.rag_service.process_query", return_value=processed),
            patch(
                "app.services.rag_service.retrieve_relevant_documents",
                side_effect=RuntimeError("/private/vector/database"),
            ),
            patch.object(rag_service.settings, "reranker_type", "none"),
        ):
            chunks = await _collect_stream(
                question="retrieve this",
                conversation_id="c1",
            )

        events = _parse_sse_events(chunks)
        self.assertEqual(
            [name for name, _data in events],
            ["routing", "status", "error", "done"],
        )
        self.assertEqual(events[-2][1]["phase"], "retrieval")
        self.assertEqual(
            events[-2][1]["message"],
            "Unable to retrieve relevant documents.",
        )
        self.assertNotIn("/private/vector/database", json.dumps(events))

    async def test_rerank_failure_emits_error_then_done(self):
        routing_memory = SimpleNamespace(messages=[], summary="")
        processed = {
            "needs_rag": True,
            "intent": "question_answering",
            "rewritten_query": "rewritten",
            "direct_answer": None,
        }
        retrieved = [
            (Document(page_content=f"document-{index}", metadata={}), 0.9 - index / 10)
            for index in range(6)
        ]
        with (
            patch(
                "app.services.rag_service.resolve_conversation_memory",
                return_value=object(),
            ),
            patch(
                "app.services.rag_service.prepare_routing_memory",
                return_value=routing_memory,
            ),
            patch("app.services.rag_service.process_query", return_value=processed),
            patch(
                "app.services.rag_service.retrieve_relevant_documents",
                return_value=retrieved,
            ),
            patch(
                "app.services.rag_service._rerank_results",
                side_effect=RuntimeError("model path /private/reranker"),
            ),
            patch.object(rag_service.settings, "reranker_type", "cross_encoder"),
            patch.object(rag_service.settings, "reranker_candidate_top_n", 20),
        ):
            chunks = await _collect_stream(
                question="rerank this",
                conversation_id="c1",
            )

        events = _parse_sse_events(chunks)
        self.assertEqual(events[-2][0], "error")
        self.assertEqual(events[-2][1]["phase"], "rerank")
        self.assertEqual(events[-1][0], "done")
        self.assertNotIn("/private/reranker", json.dumps(events))

    async def test_generation_failure_does_not_persist_partial_answer(self):
        routing_memory = SimpleNamespace(messages=[], summary="")
        processed = {
            "needs_rag": True,
            "intent": "question_answering",
            "rewritten_query": "rewritten",
            "direct_answer": None,
        }
        context_plan = SimpleNamespace(
            documents=[],
            history=[],
            summary="",
            included_document_count=0,
        )

        async def failing_generation(**_kwargs):
            raise RuntimeError("provider URL http://secret")
            yield ""

        with (
            patch(
                "app.services.rag_service.resolve_conversation_memory",
                return_value=object(),
            ),
            patch(
                "app.services.rag_service.prepare_routing_memory",
                return_value=routing_memory,
            ),
            patch("app.services.rag_service.process_query", return_value=processed),
            patch(
                "app.services.rag_service.retrieve_relevant_documents",
                return_value=[],
            ),
            patch(
                "app.services.rag_service.prepare_generation_context",
                return_value=context_plan,
            ),
            patch(
                "app.services.rag_service.generate_answer_stream",
                failing_generation,
            ),
            patch(
                "app.services.rag_service._schedule_completed_query"
            ) as schedule_mock,
            patch.object(rag_service.settings, "reranker_type", "none"),
        ):
            chunks = await _collect_stream(
                question="generate this",
                conversation_id="c1",
            )

        events = _parse_sse_events(chunks)
        self.assertEqual(events[-2][0], "error")
        self.assertEqual(events[-2][1]["phase"], "generation")
        self.assertEqual(events[-1][0], "done")
        self.assertNotIn("http://secret", json.dumps(events))
        schedule_mock.assert_not_called()

    async def test_generation_cancellation_does_not_persist_partial_answer(self):
        routing_memory = SimpleNamespace(messages=[], summary="")
        processed = {
            "needs_rag": True,
            "intent": "question_answering",
            "rewritten_query": "rewritten",
            "direct_answer": None,
        }
        context_plan = SimpleNamespace(
            documents=[],
            history=[],
            summary="",
            included_document_count=0,
        )

        async def cancelled_generation(**_kwargs):
            raise asyncio.CancelledError
            yield ""

        with (
            patch(
                "app.services.rag_service.resolve_conversation_memory",
                return_value=object(),
            ),
            patch(
                "app.services.rag_service.prepare_routing_memory",
                return_value=routing_memory,
            ),
            patch("app.services.rag_service.process_query", return_value=processed),
            patch(
                "app.services.rag_service.retrieve_relevant_documents",
                return_value=[],
            ),
            patch(
                "app.services.rag_service.prepare_generation_context",
                return_value=context_plan,
            ),
            patch(
                "app.services.rag_service.generate_answer_stream",
                cancelled_generation,
            ),
            patch(
                "app.services.rag_service._schedule_completed_query"
            ) as schedule_mock,
            patch.object(rag_service.settings, "reranker_type", "none"),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await _collect_stream(
                    question="cancel this",
                    conversation_id="c1",
                )

        schedule_mock.assert_not_called()

    async def test_blocking_pipeline_stages_run_through_to_thread(self):
        routing_memory = SimpleNamespace(messages=[], summary="")
        processed = {
            "needs_rag": True,
            "intent": "question_answering",
            "rewritten_query": "rewritten",
            "direct_answer": None,
        }
        retrieved = [
            (Document(page_content=f"document-{index}", metadata={}), 0.9 - index / 10)
            for index in range(6)
        ]
        reranked = retrieved[:3]
        context_plan = SimpleNamespace(
            documents=[document for document, _score in reranked],
            history=[],
            summary="",
            included_document_count=3,
        )
        threaded_functions = []

        async def recording_to_thread(function, /, *args, **kwargs):
            threaded_functions.append(function)
            return function(*args, **kwargs)

        async def successful_generation(**_kwargs):
            yield "answer"

        with (
            patch(
                "app.services.rag_service.resolve_conversation_memory",
                return_value=object(),
            ) as resolve_mock,
            patch(
                "app.services.rag_service.prepare_routing_memory",
                return_value=routing_memory,
            ) as prepare_routing_mock,
            patch(
                "app.services.rag_service.process_query",
                return_value=processed,
            ) as process_mock,
            patch(
                "app.services.rag_service.retrieve_relevant_documents",
                return_value=retrieved,
            ) as retrieval_mock,
            patch(
                "app.services.rag_service._rerank_results",
                return_value=reranked,
            ) as rerank_mock,
            patch(
                "app.services.rag_service.prepare_generation_context",
                return_value=context_plan,
            ) as generation_context_mock,
            patch(
                "app.services.rag_service.generate_answer_stream",
                successful_generation,
            ),
            patch("app.services.rag_service.asyncio.to_thread", recording_to_thread),
            patch(
                "app.services.rag_service._schedule_completed_query"
            ) as schedule_mock,
            patch.object(rag_service.settings, "reranker_type", "cross_encoder"),
            patch.object(rag_service.settings, "reranker_candidate_top_n", 20),
            patch.object(rag_service.settings, "reranker_final_top_k", 3),
        ):
            chunks = await _collect_stream(
                question="full pipeline",
                conversation_id="c1",
            )

        self.assertIn(resolve_mock, threaded_functions)
        self.assertIn(prepare_routing_mock, threaded_functions)
        self.assertIn(process_mock, threaded_functions)
        self.assertIn(retrieval_mock, threaded_functions)
        self.assertIn(rerank_mock, threaded_functions)
        self.assertIn(generation_context_mock, threaded_functions)
        self.assertEqual(_parse_sse_events(chunks)[-1][0], "done")
        self.assertEqual(retrieval_mock.call_args.kwargs["top_k"], 20)
        self.assertEqual(rerank_mock.call_args.args[2], 3)
        self.assertEqual(schedule_mock.call_args.kwargs["top_k"], 3)


if __name__ == "__main__":
    unittest.main()

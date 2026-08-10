"""Server-side memory restoration, compaction, and token-budget tests."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.context_manager import (
    CompactionStatus,
    ContextWindowExceededError,
    ConversationMemory,
    compact_conversation_memory,
    compact_conversation_memory_once,
    count_tokens,
    fit_memory_to_budget,
    parse_structured_summary,
    prepare_generation_context,
    render_stored_summary,
    resolve_conversation_memory,
)
from app.rag.conversation_store import ConversationStore
from app.schemas.rag import Message


class ContextManagerTest(unittest.TestCase):
    def test_token_budget_keeps_newest_messages(self):
        memory = ConversationMemory(
            summary="The user is designing a local RAG system.",
            messages=[
                Message(role="user", content=f"old question {index} " * 20)
                if index % 2 == 0
                else Message(role="assistant", content=f"old answer {index} " * 20)
                for index in range(10)
            ],
            source="test",
        )

        with patch.multiple(
            settings,
            context_short_term_max_turns=6,
            context_short_term_max_tokens=180,
        ):
            prepared = fit_memory_to_budget(memory, max_tokens=180)

        self.assertLessEqual(prepared.token_count, 180)
        self.assertGreater(prepared.dropped_messages, 0)
        self.assertEqual(len(prepared.messages) % 2, 0)
        self.assertEqual(
            [message.role for message in prepared.messages[-2:]],
            ["user", "assistant"],
        )
        self.assertEqual(prepared.messages[-1].role, "assistant")
        self.assertIn("old answer 9", prepared.messages[-1].content)
        self.assertTrue(prepared.summary)

    def test_short_term_window_keeps_latest_complete_turns(self):
        memory = ConversationMemory(
            summary="",
            messages=[
                Message(
                    role="user" if index % 2 == 0 else "assistant",
                    content=f"message-{index}",
                    turn_id=f"turn-{index // 2}",
                )
                for index in range(10)
            ],
            source="test",
        )

        with patch.multiple(
            settings,
            context_short_term_max_turns=2,
            context_short_term_max_tokens=4_096,
        ):
            prepared = fit_memory_to_budget(memory, max_tokens=4_096)

        self.assertEqual(prepared.included_turns, 2)
        self.assertEqual(prepared.included_pending_turns, 3)
        self.assertEqual(prepared.dropped_pending_turns, 0)
        self.assertEqual(prepared.dropped_turns, 0)
        self.assertEqual(
            [message.content for message in prepared.pending_messages],
            [
                "message-0",
                "message-1",
                "message-2",
                "message-3",
                "message-4",
                "message-5",
            ],
        )
        self.assertEqual(
            [message.content for message in prepared.messages],
            ["message-6", "message-7", "message-8", "message-9"],
        )

    def test_oversized_newest_turn_is_truncated_as_a_pair(self):
        memory = ConversationMemory(
            summary="",
            messages=[
                Message(role="user", content="question " * 500, turn_id="turn-1"),
                Message(role="assistant", content="answer " * 500, turn_id="turn-1"),
            ],
            source="test",
        )

        with patch.multiple(
            settings,
            context_short_term_max_turns=6,
            context_short_term_max_tokens=120,
        ):
            prepared = fit_memory_to_budget(memory, max_tokens=120)

        self.assertEqual(prepared.included_turns, 1)
        self.assertEqual(
            [message.role for message in prepared.messages],
            ["user", "assistant"],
        )
        self.assertLessEqual(prepared.recent_tokens, 120)
        self.assertTrue(all(message.content for message in prepared.messages))

    def test_orphan_message_is_not_exposed_as_short_term_memory(self):
        memory = ConversationMemory(
            summary="",
            messages=[
                Message(role="assistant", content="orphan", turn_id="broken"),
                Message(role="user", content="question", turn_id="turn-1"),
                Message(role="assistant", content="answer", turn_id="turn-1"),
            ],
            source="test",
        )

        prepared = fit_memory_to_budget(memory, max_tokens=4_096)

        self.assertEqual(
            [message.content for message in prepared.messages],
            ["question", "answer"],
        )

    @patch("app.rag.context_manager.get_conversation_store")
    def test_server_history_is_merged_with_unpersisted_client_tail(self, get_store_mock):
        store = MagicMock()
        store.get_context_state.return_value = {
            "summary": "Earlier decisions",
            "summary_revision": 7,
            "summary_token_count": 9,
            "messages": [
                {"id": 3, "role": "user", "content": "persisted question"},
                {"id": 4, "role": "assistant", "content": "persisted answer"},
            ],
        }
        get_store_mock.return_value = store

        memory = resolve_conversation_memory(
            "conversation-1",
            [
                Message(role="assistant", content="persisted answer"),
                Message(role="user", content="not persisted yet"),
                Message(role="assistant", content="new answer"),
            ],
        )

        self.assertEqual(memory.source, "server")
        self.assertEqual(memory.summary, "Earlier decisions")
        self.assertEqual(memory.summary_revision, 7)
        self.assertEqual(memory.summary_token_count, 9)
        self.assertEqual(
            [message.content for message in memory.messages],
            [
                "persisted question",
                "persisted answer",
                "not persisted yet",
                "new answer",
            ],
        )

    def test_generation_budget_covers_history_documents_and_output_reserve(self):
        memory = ConversationMemory(
            summary="Long-term project constraints " * 80,
            messages=[
                Message(role="user", content=f"question {index} " * 80)
                if index % 2 == 0
                else Message(role="assistant", content=f"answer {index} " * 80)
                for index in range(12)
            ],
            source="test",
        )
        documents = [
            Document(
                page_content=(f"document {index} technical content " * 250),
                metadata={"source": f"doc-{index}.md"},
            )
            for index in range(5)
        ]

        with patch.multiple(
            settings,
            llm_context_window=2_000,
            llm_reserved_output_tokens=256,
            context_safety_margin_tokens=128,
            context_history_max_tokens=500,
            context_document_min_tokens=600,
        ):
            plan = prepare_generation_context("Explain the design", memory, documents)

        self.assertLessEqual(plan.input_tokens, 2_000 - 256 - 128)
        self.assertLessEqual(plan.history_tokens, 500)
        self.assertGreater(plan.summary_tokens, 0)
        self.assertGreater(plan.included_history_turns, 0)
        self.assertGreater(plan.dropped_history_turns, 0)
        self.assertGreater(plan.document_tokens, 0)
        self.assertGreater(plan.dropped_history_messages, 0)
        self.assertGreater(plan.dropped_documents, 0)

    def test_oversized_question_is_rejected_before_llm_call(self):
        memory = ConversationMemory(summary="", messages=[], source="test")
        with patch.multiple(
            settings,
            llm_context_window=512,
            llm_reserved_output_tokens=128,
            context_safety_margin_tokens=64,
        ):
            with self.assertRaises(ContextWindowExceededError):
                prepare_generation_context("超长问题" * 2_000, memory, [])

    def test_background_compaction_advances_summary_cursor(self):
        store = MagicMock()
        store.get_context_state.return_value = {
            "summary": "Existing memory.",
            "summary_revision": 2,
            "messages": [
                {
                    "id": index,
                    "role": "user" if index % 2 else "assistant",
                    "content": f"m{index}",
                    "turn_id": f"turn-{(index - 1) // 2}",
                }
                for index in range(1, 7)
            ],
        }
        store.update_context_summary.return_value = True
        llm = MagicMock()
        llm.invoke.return_value.content = """{
            "schema_version": 1,
            "summary": "Updated faithful memory.",
            "goals": ["Ship the context redesign"],
            "constraints": [],
            "decisions": ["Keep complete turns"],
            "open_questions": [],
            "entities": {"project": "Local RAG"}
        }"""

        with (
            patch.multiple(
                settings,
                context_summary_enabled=True,
                context_short_term_max_turns=1,
                context_summary_batch_turns=2,
            ),
            patch("app.rag.context_manager.get_llm", return_value=llm),
        ):
            updated = compact_conversation_memory("c1", store=store)

        self.assertTrue(updated)
        kwargs = store.update_context_summary.call_args.kwargs
        self.assertEqual(kwargs["through_message_id"], 4)
        self.assertEqual(kwargs["summary_schema_version"], 1)
        self.assertGreater(kwargs["summary_token_count"], 0)
        payload = parse_structured_summary(kwargs["summary"])
        self.assertEqual(payload["summary"], "Updated faithful memory.")
        self.assertEqual(payload["decisions"], ["Keep complete turns"])

    def test_invalid_structured_summary_does_not_advance_cursor(self):
        store = MagicMock()
        store.get_context_state.return_value = {
            "summary": "",
            "messages": [
                {
                    "id": index,
                    "role": "user" if index % 2 else "assistant",
                    "content": f"m{index}",
                    "turn_id": f"turn-{(index - 1) // 2}",
                }
                for index in range(1, 5)
            ],
        }
        llm = MagicMock()
        llm.invoke.return_value.content = "not-json"

        with (
            patch.multiple(
                settings,
                context_summary_enabled=True,
                context_short_term_max_turns=1,
                context_summary_batch_turns=1,
            ),
            patch("app.rag.context_manager.get_llm", return_value=llm),
        ):
            updated = compact_conversation_memory("c1", store=store)

        self.assertFalse(updated)
        store.update_context_summary.assert_not_called()

    def test_compaction_can_trigger_on_token_pressure_before_turn_threshold(self):
        store = MagicMock()
        store.get_context_state.return_value = {
            "summary": "",
            "summary_revision": 0,
            "summary_token_count": 0,
            "messages": [
                {
                    "id": index,
                    "role": "user" if index % 2 else "assistant",
                    "content": "large memory segment " * 80,
                    "turn_id": f"turn-{(index - 1) // 2}",
                }
                for index in range(1, 5)
            ],
        }
        store.update_context_summary.return_value = True
        llm = MagicMock()
        llm.invoke.return_value.content = (
            '{"schema_version":1,"summary":"Compressed facts",'
            '"goals":[],"constraints":[],"decisions":[],'
            '"open_questions":[],"entities":{}}'
        )

        with (
            patch.multiple(
                settings,
                context_summary_enabled=True,
                context_short_term_max_turns=1,
                context_summary_batch_turns=100,
                context_summary_trigger_tokens=128,
            ),
            patch("app.rag.context_manager.get_llm", return_value=llm),
        ):
            outcome = compact_conversation_memory_once("c1", store=store)

        self.assertEqual(outcome.status, CompactionStatus.COMPACTED)
        self.assertEqual(outcome.through_message_id, 2)
        self.assertEqual(outcome.compacted_turns, 1)

    def test_stale_summary_cursor_returns_typed_follow_up_outcome(self):
        store = MagicMock()
        store.get_context_state.return_value = {
            "summary": "",
            "summary_revision": 4,
            "summary_token_count": 0,
            "messages": [
                {
                    "id": index,
                    "role": "user" if index % 2 else "assistant",
                    "content": f"m{index}",
                    "turn_id": f"turn-{(index - 1) // 2}",
                }
                for index in range(1, 5)
            ],
        }
        store.update_context_summary.return_value = False
        llm = MagicMock()
        llm.invoke.return_value.content = (
            '{"schema_version":1,"summary":"Compressed facts",'
            '"goals":[],"constraints":[],"decisions":[],'
            '"open_questions":[],"entities":{}}'
        )

        with (
            patch.multiple(
                settings,
                context_summary_enabled=True,
                context_short_term_max_turns=1,
                context_summary_batch_turns=1,
            ),
            patch("app.rag.context_manager.get_llm", return_value=llm),
        ):
            outcome = compact_conversation_memory_once("c1", store=store)

        self.assertEqual(outcome.status, CompactionStatus.STALE)
        self.assertTrue(outcome.needs_follow_up)

    def test_structured_summary_is_rendered_with_stable_sections(self):
        raw = """{
            "schema_version": 1,
            "summary": "A local RAG redesign.",
            "goals": ["Keep context faithful"],
            "constraints": ["No half turns"],
            "decisions": [],
            "open_questions": ["How should profile memory work?"],
            "entities": {"project": "Local RAG"}
        }"""

        rendered = render_stored_summary(raw)

        self.assertIn("Overview: A local RAG redesign.", rendered)
        self.assertIn("Goals:\n- Keep context faithful", rendered)
        self.assertIn("Entities:\n- project: Local RAG", rendered)

    def test_tokenizer_handles_chinese_without_character_heuristic(self):
        self.assertGreater(count_tokens("这是一个中文上下文预算测试。"), 1)


class ConversationContextStoreTest(unittest.TestCase):
    def test_legacy_conversation_database_is_migrated_in_place(self):
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
                connection.execute(
                    "INSERT INTO conversations VALUES ('legacy', 'Legacy', 1, 1)"
                )
                connection.commit()

            store = ConversationStore(database)
            state = store.get_context_state("legacy")

            self.assertEqual(state["summary"], "")
            self.assertEqual(state["summary_through_message_id"], 0)
            self.assertEqual(state["summary_schema_version"], 0)
            self.assertEqual(state["summary_revision"], 0)
            self.assertEqual(state["summary_token_count"], 0)

    def test_summary_schema_and_cursor_preserve_full_message_history(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conversations.db")
            store.save_exchange("c1", "question one", "answer one")
            store.save_exchange("c1", "question two", "answer two")

            before = store.get_context_state("c1")
            self.assertEqual(len(before["messages"]), 4)

            through_id = before["messages"][1]["id"]
            summary = (
                '{"schema_version":1,"summary":"first exchange summary",'
                '"goals":[],"constraints":[],"decisions":[],'
                '"open_questions":[],"entities":{}}'
            )
            self.assertTrue(
                store.update_context_summary(
                    "c1",
                    summary,
                    through_id,
                    summary_schema_version=1,
                    summary_token_count=25,
                )
            )

            context_state = store.get_context_state("c1")
            full_conversation = store.get_conversation("c1")
            self.assertEqual(context_state["summary"], summary)
            self.assertEqual(context_state["summary_schema_version"], 1)
            self.assertEqual(context_state["summary_revision"], 1)
            self.assertEqual(context_state["summary_token_count"], 25)
            self.assertEqual(len(context_state["messages"]), 2)
            self.assertEqual(len(full_conversation["messages"]), 4)

    def test_legacy_half_turn_cursor_is_repaired_at_read_boundary(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conversations.db")
            store.save_exchange(
                "c1",
                "question one",
                "answer one",
                turn_id="turn-1",
            )
            before = store.get_context_state("c1")
            user_message_id = before["messages"][0]["id"]
            self.assertTrue(
                store.update_context_summary(
                    "c1",
                    "legacy partial summary",
                    user_message_id,
                    summary_schema_version=0,
                )
            )

            state = store.get_context_state("c1")

            self.assertEqual(
                [message["role"] for message in state["messages"]],
                ["user", "assistant"],
            )
            self.assertEqual(
                [message["turn_id"] for message in state["messages"]],
                ["turn-1", "turn-1"],
            )


if __name__ == "__main__":
    unittest.main()

"""Server-side memory restoration, compaction, and token-budget tests."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.context_manager import (
    ContextWindowExceededError,
    ConversationMemory,
    compact_conversation_memory,
    count_tokens,
    fit_memory_to_budget,
    prepare_generation_context,
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

        prepared = fit_memory_to_budget(memory, max_tokens=180)

        self.assertLessEqual(prepared.token_count, 180)
        self.assertGreater(prepared.dropped_messages, 0)
        self.assertEqual(prepared.messages[-1].role, "assistant")
        self.assertIn("old answer 9", prepared.messages[-1].content)
        self.assertTrue(prepared.summary)

    @patch("app.rag.context_manager.get_conversation_store")
    def test_server_history_is_merged_with_unpersisted_client_tail(self, get_store_mock):
        store = MagicMock()
        store.get_context_state.return_value = {
            "summary": "Earlier decisions",
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
            "messages": [
                {"id": index, "role": "user" if index % 2 else "assistant", "content": f"m{index}"}
                for index in range(1, 7)
            ],
        }
        store.update_context_summary.return_value = True
        llm = MagicMock()
        llm.invoke.return_value.content = "Updated faithful memory."

        with (
            patch.multiple(
                settings,
                context_summary_enabled=True,
                context_summary_keep_recent_messages=2,
                context_summary_batch_messages=2,
            ),
            patch("app.rag.context_manager.get_llm", return_value=llm),
        ):
            updated = compact_conversation_memory("c1", store=store)

        self.assertTrue(updated)
        kwargs = store.update_context_summary.call_args.kwargs
        self.assertEqual(kwargs["through_message_id"], 4)
        self.assertEqual(kwargs["summary"], "Updated faithful memory.")

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

    def test_summary_schema_and_cursor_preserve_full_message_history(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conversations.db")
            store.save_exchange("c1", "question one", "answer one")
            store.save_exchange("c1", "question two", "answer two")

            before = store.get_context_state("c1")
            self.assertEqual(len(before["messages"]), 4)

            through_id = before["messages"][1]["id"]
            self.assertTrue(
                store.update_context_summary("c1", "first exchange summary", through_id)
            )

            context_state = store.get_context_state("c1")
            full_conversation = store.get_conversation("c1")
            self.assertEqual(context_state["summary"], "first exchange summary")
            self.assertEqual(len(context_state["messages"]), 2)
            self.assertEqual(len(full_conversation["messages"]), 4)


if __name__ == "__main__":
    unittest.main()

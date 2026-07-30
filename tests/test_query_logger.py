"""Concurrent JSONL query trace tests."""

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app.rag.query_logger import log_rag_query


class QueryLoggerTest(unittest.TestCase):
    def test_legacy_call_signature_remains_supported(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_dir = Path(tmp_dir) / "history"
            jsonl_path = history_dir / "queries.jsonl"
            with (
                patch("app.rag.query_logger.HISTORY_DIR", history_dir),
                patch("app.rag.query_logger.JSONL_PATH", jsonl_path),
            ):
                log_rag_query("q", "q", "unknown", [], "a", 5)

            record = json.loads(jsonl_path.read_text(encoding="utf-8"))
            self.assertNotIn("conversation_id", record)
            self.assertNotIn("routing", record)
            self.assertNotIn("stage_timings_ms", record)

    def test_concurrent_writes_produce_complete_json_lines_with_trace_fields(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_dir = Path(tmp_dir) / "history"
            jsonl_path = history_dir / "queries.jsonl"

            def write_record(index: int):
                log_rag_query(
                    f"question-{index}",
                    f"rewritten-{index}",
                    "question_answering",
                    [],
                    f"answer-{index}",
                    5,
                    conversation_id=f"conversation-{index}",
                    routing="rag",
                    stage_timings={"routing": 0.012, "total": 0.034},
                    turn_id=f"turn-{index}",
                )

            with (
                patch("app.rag.query_logger.HISTORY_DIR", history_dir),
                patch("app.rag.query_logger.JSONL_PATH", jsonl_path),
                ThreadPoolExecutor(max_workers=8) as pool,
            ):
                list(pool.map(write_record, range(50)))

            lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 50)
            records = [json.loads(line) for line in lines]
            self.assertEqual(
                {record["turn_id"] for record in records},
                {f"turn-{index}" for index in range(50)},
            )
            self.assertTrue(all(record["routing"] == "rag" for record in records))
            self.assertTrue(
                all(record["stage_timings_ms"]["routing"] == 12.0 for record in records)
            )


if __name__ == "__main__":
    unittest.main()

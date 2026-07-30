"""Query processor structured-output and fail-open tests."""

import unittest

from app.rag.query_processor import _parse_query_processing_response


class QueryProcessorParsingTest(unittest.TestCase):
    def test_parses_retrieval_json(self):
        result = _parse_query_processing_response(
            """
            {
              "needs_rag": true,
              "intent": "fact_lookup",
              "rewritten_query": "server-side RAG context budget",
              "direct_answer": null
            }
            """
        )

        self.assertTrue(result["needs_rag"])
        self.assertEqual(result["intent"], "fact_lookup")
        self.assertEqual(
            result["rewritten_query"],
            "server-side RAG context budget",
        )
        self.assertIsNone(result["direct_answer"])

    def test_parses_json_code_fence(self):
        result = _parse_query_processing_response(
            """```json
            {"needs_rag": false, "intent": "chitchat",
             "rewritten_query": null, "direct_answer": "Hello!"}
            ```"""
        )

        self.assertFalse(result["needs_rag"])
        self.assertEqual(result["direct_answer"], "Hello!")

    def test_supports_legacy_line_protocol(self):
        result = _parse_query_processing_response(
            "ROUTING: YES\nINTENT: comparison\nQUERY: compare two designs"
        )

        self.assertTrue(result["needs_rag"])
        self.assertEqual(result["intent"], "comparison")
        self.assertEqual(result["rewritten_query"], "compare two designs")

    def test_missing_routing_is_invalid_and_must_fail_open(self):
        self.assertIsNone(
            _parse_query_processing_response(
                "INTENT: question_answering\nQUERY: silently malformed"
            )
        )

    def test_direct_route_without_answer_is_invalid(self):
        self.assertIsNone(
            _parse_query_processing_response(
                '{"needs_rag": false, "intent": "chitchat"}'
            )
        )


if __name__ == "__main__":
    unittest.main()

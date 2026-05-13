import unittest

from evaluation.retrieval_metrics.matching import (
    RelevantSource,
    build_retrieved_item,
    match_retrieved_to_relevant_sources,
)


class RetrievalMatchingTest(unittest.TestCase):
    def test_matches_by_file_path_and_text_snippet(self):
        item = build_retrieved_item(
            content="The retrieval pipeline loads, splits, embeds, and stores chunks.",
            metadata={"file_path": "docs/rag.md", "chunk_index": 2},
        )

        matched = match_retrieved_to_relevant_sources(
            [item],
            [RelevantSource(file_path="docs/rag.md", text="splits, embeds", relevance=3)],
        )

        self.assertEqual(matched.retrieved_ids, ["docs/rag.md#chunk:2"])
        self.assertEqual(matched.relevant_ids, {"docs/rag.md#chunk:2"})
        self.assertEqual(matched.relevance_scores["docs/rag.md#chunk:2"], 3)

    def test_unmatched_label_stays_in_relevance_scores_for_ndcg_ideal(self):
        item = build_retrieved_item(
            content="Unrelated content",
            metadata={"file_path": "docs/other.md", "chunk_index": 1},
        )

        matched = match_retrieved_to_relevant_sources(
            [item],
            [RelevantSource(file_path="docs/rag.md", relevance=2)],
        )

        self.assertEqual(matched.relevant_ids, set())
        self.assertEqual(matched.relevance_scores, {"expected:0": 2})

    def test_content_hash_id_is_used_when_chunk_index_is_missing(self):
        item = build_retrieved_item(
            content="Stable content",
            metadata={"file_path": "docs/rag.md"},
        )

        self.assertTrue(item.id.startswith("docs/rag.md#content:"))

    def test_snippet_matching_is_case_and_whitespace_tolerant(self):
        item = build_retrieved_item(
            content="Employees may   request\nremote work after manager approval.",
            metadata={"file_path": "handbook/hr.md", "chunk_index": 4},
        )

        matched = match_retrieved_to_relevant_sources(
            [item],
            [RelevantSource(file_path="handbook/hr.md", text="REMOTE work after", relevance=2)],
        )

        self.assertEqual(matched.relevant_ids, {"handbook/hr.md#chunk:4"})

    def test_source_name_can_match_uploaded_documents_without_file_path(self):
        item = build_retrieved_item(
            content="The customer escalation workflow starts with severity triage.",
            metadata={"source": "support_playbook.pdf", "file_name": "support_playbook.pdf", "chunk_index": 7},
        )

        matched = match_retrieved_to_relevant_sources(
            [item],
            [RelevantSource(source="support_playbook.pdf", text="severity triage")],
        )

        self.assertEqual(matched.relevant_ids, {"support_playbook.pdf#chunk:7"})

    def test_wrong_file_with_right_snippet_does_not_count_as_relevant(self):
        item = build_retrieved_item(
            content="The deployment checklist requires rollback verification.",
            metadata={"file_path": "archive/old_deploy.md", "chunk_index": 1},
        )

        matched = match_retrieved_to_relevant_sources(
            [item],
            [RelevantSource(file_path="docs/current_deploy.md", text="rollback verification")],
        )

        self.assertEqual(matched.relevant_ids, set())


if __name__ == "__main__":
    unittest.main()

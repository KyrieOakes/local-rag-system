"""
检索匹配逻辑单元测试。

测试 evaluation/retrieval_metrics/matching.py 的匹配函数：
- 按 file_path + text 片段匹配检索结果
- 未匹配的标注仍保留为稳定 evidence（Recall/NDCG 分母）
- 无 chunk_index 时使用内容哈希生成 ID
- 旧数据没有 evidence_id 时生成稳定哈希 ID
- 文本匹配对大小写和空白容忍
- 按 source/file_name 匹配（无需 file_path）
- 错误文件+正确片段不算匹配

运行：python -m unittest tests.test_retrieval_matching
"""
import unittest

from evaluation.retrieval_metrics.matching import (
    RelevantSource,
    build_retrieved_item,
    make_evidence_id,
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
            [
                RelevantSource(
                    file_path="docs/rag.md",
                    text="splits, embeds",
                    relevance=3,
                    evidence_id="rag-pipeline",
                )
            ],
        )

        self.assertEqual(matched.retrieved_ids, ["docs/rag.md#chunk:2"])
        self.assertEqual(matched.evidence_ids, ["rag-pipeline"])
        self.assertEqual(matched.matched_evidence_ids, {"rag-pipeline"})
        self.assertEqual(matched.evidence_scores["rag-pipeline"], 3)
        self.assertEqual(matched.matched_chunk_ids, {"docs/rag.md#chunk:2"})

    def test_unmatched_label_stays_in_gold_evidence_denominator(self):
        item = build_retrieved_item(
            content="Unrelated content",
            metadata={"file_path": "docs/other.md", "chunk_index": 1},
        )

        matched = match_retrieved_to_relevant_sources(
            [item],
            [
                RelevantSource(
                    file_path="docs/rag.md",
                    relevance=2,
                    evidence_id="expected-rag",
                )
            ],
        )

        self.assertEqual(matched.matched_evidence_ids, set())
        self.assertEqual(matched.evidence_ids, ["expected-rag"])
        self.assertEqual(matched.evidence_scores, {"expected-rag": 2})

    def test_legacy_label_without_id_gets_stable_evidence_hash(self):
        first = RelevantSource(
            file_path="docs/rag.md",
            text="vector retrieval",
            relevance=2,
        )
        same_label = RelevantSource(
            file_path="docs/rag.md",
            text="vector   retrieval",
            relevance=3,
        )

        self.assertEqual(make_evidence_id(first), make_evidence_id(same_label))
        self.assertTrue(make_evidence_id(first).startswith("evidence:"))

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
            [
                RelevantSource(
                    file_path="handbook/hr.md",
                    text="REMOTE work after",
                    relevance=2,
                    evidence_id="remote-work",
                )
            ],
        )

        self.assertEqual(matched.matched_evidence_ids, {"remote-work"})

    def test_source_name_can_match_uploaded_documents_without_file_path(self):
        item = build_retrieved_item(
            content="The customer escalation workflow starts with severity triage.",
            metadata={"source": "support_playbook.pdf", "file_name": "support_playbook.pdf", "chunk_index": 7},
        )

        matched = match_retrieved_to_relevant_sources(
            [item],
            [
                RelevantSource(
                    source="support_playbook.pdf",
                    text="severity triage",
                    evidence_id="severity-triage",
                )
            ],
        )

        self.assertEqual(matched.matched_evidence_ids, {"severity-triage"})

    def test_wrong_file_with_right_snippet_does_not_count_as_relevant(self):
        item = build_retrieved_item(
            content="The deployment checklist requires rollback verification.",
            metadata={"file_path": "archive/old_deploy.md", "chunk_index": 1},
        )

        matched = match_retrieved_to_relevant_sources(
            [item],
            [
                RelevantSource(
                    file_path="docs/current_deploy.md",
                    text="rollback verification",
                    evidence_id="rollback",
                )
            ],
        )

        self.assertEqual(matched.matched_evidence_ids, set())


if __name__ == "__main__":
    unittest.main()

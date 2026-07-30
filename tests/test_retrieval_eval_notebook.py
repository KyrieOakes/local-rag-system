"""Regression tests for executable logic embedded in the retrieval notebook."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np
from langchain_core.documents import Document

from app.rag.reranker import build_rerank_candidates
from evaluation.retrieval_metrics.evaluator import evaluate_retrieval_case
from evaluation.retrieval_metrics.matching import (
    RelevantSource,
    RetrievedItem,
    build_retrieved_item,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = ROOT_DIR / "evaluation" / "retrieval_eval_pipeline.ipynb"


def _notebook_cells() -> list[str]:
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    sources = []
    for cell in notebook["cells"]:
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        sources.append(source)
    return sources


def _load_notebook_functions(
    names: set[str],
    initial_globals: dict[str, Any],
) -> dict[str, Any]:
    nodes: list[ast.stmt] = [
        ast.ImportFrom(
            module="__future__",
            names=[ast.alias(name="annotations")],
            level=0,
        )
    ]
    found = set()
    for source in _notebook_cells():
        sanitized = "\n".join(
            line for line in source.splitlines()
            if not line.lstrip().startswith("%")
        )
        tree = ast.parse(sanitized)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
                nodes.append(node)
                found.add(node.name)

    missing = names - found
    if missing:
        raise AssertionError(f"Notebook functions not found: {sorted(missing)}")

    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    namespace = dict(initial_globals)
    exec(compile(module, str(NOTEBOOK_PATH), "exec"), namespace)
    return namespace


class RetrievalEvaluationNotebookTest(unittest.TestCase):
    def test_all_code_cells_compile_after_removing_ipython_magic(self):
        for index, source in enumerate(_notebook_cells()):
            sanitized = "\n".join(
                line for line in source.splitlines()
                if not line.lstrip().startswith("%")
            )
            with self.subTest(cell=index):
                compile(sanitized, f"{NOTEBOOK_PATH}:cell-{index}", "exec")

    def test_live_retrieval_really_invokes_reranker(self):
        namespace = _load_notebook_functions(
            {"_build_notebook_reranker", "run_live_retrieval"},
            {
                "Any": Any,
                "RetrievedItem": RetrievedItem,
                "build_retrieved_item": build_retrieved_item,
                "USE_QUERY_PROCESSOR": False,
                "RERANK_ENABLED": True,
                "EFFECTIVE_RERANK_ENABLED": True,
                "RERANK_TOP_N": 20,
                "RERANKER_TYPE": "hybrid",
                "TOP_K": 5,
            },
        )
        fetch_sizes = []
        documents = [
            Document(
                page_content=f"document-{index}",
                metadata={"file_path": "docs.md", "chunk_index": index},
            )
            for index in range(20)
        ]

        def retrieve(_question: str, *, top_k: int):
            fetch_sizes.append(top_k)
            return [(document, float(index)) for index, document in enumerate(documents)]

        class RecordingReranker:
            def __init__(self):
                self.top_k = None

            def rerank(self, *, query, candidates, top_k):
                self.top_k = top_k
                ranked = list(reversed(candidates))[:top_k]
                result = []
                for rank, candidate in enumerate(ranked):
                    candidate.document.metadata["rerank_score"] = float(top_k - rank)
                    result.append((candidate.document, float(top_k - rank)))
                return result

        reranker = RecordingReranker()
        items, execution = namespace["run_live_retrieval"](
            "question",
            10,
            retrieve_fn=retrieve,
            reranker=reranker,
            build_candidates_fn=build_rerank_candidates,
        )

        self.assertEqual(fetch_sizes, [20])
        self.assertEqual(reranker.top_k, 10)
        self.assertEqual(len(items), 10)
        self.assertTrue(execution["attempted"])
        self.assertTrue(execution["applied"])
        self.assertEqual(execution["reason"], "applied")

    def test_demo_is_deterministic_and_never_claims_rerank(self):
        namespace = _load_notebook_functions(
            {"_stable_demo_seed", "run_demo_retrieval"},
            {
                "Any": Any,
                "RetrievedItem": RetrievedItem,
                "build_retrieved_item": build_retrieved_item,
                "hashlib": hashlib,
                "np": np,
                "RERANK_ENABLED": True,
            },
        )
        record = {
            "id": "q-stable",
            "question": "stable?",
            "relevant_sources": [
                {
                    "file_path": "docs.md",
                    "text": "gold evidence",
                    "relevance": 1.0,
                }
            ],
        }

        first_items, first_execution = namespace["run_demo_retrieval"](record, 10)
        second_items, second_execution = namespace["run_demo_retrieval"](record, 10)

        self.assertEqual(namespace["_stable_demo_seed"](record), 859038411)
        self.assertEqual(
            [(item.id, item.content, item.score) for item in first_items],
            [(item.id, item.content, item.score) for item in second_items],
        )
        self.assertEqual(first_execution, second_execution)
        self.assertFalse(first_execution["enabled"])
        self.assertFalse(first_execution["attempted"])
        self.assertFalse(first_execution["applied"])
        self.assertEqual(first_execution["reason"], "disabled_in_demo_mode")

    def test_primary_metrics_do_not_see_hidden_sensitivity_candidates(self):
        namespace = _load_notebook_functions(
            {"evaluate_primary_retrieval"},
            {
                "RelevantSource": RelevantSource,
                "RetrievedItem": RetrievedItem,
                "evaluate_retrieval_case": evaluate_retrieval_case,
            },
        )
        items = [
            build_retrieved_item(
                f"noise-{index}",
                {"file_path": f"noise-{index}.md", "chunk_index": index},
            )
            for index in range(5)
        ]
        items.append(
            build_retrieved_item(
                "contains target evidence",
                {"file_path": "target.md", "chunk_index": 0},
            )
        )
        relevant = [
            RelevantSource(file_path="target.md", text="target evidence")
        ]

        result = namespace["evaluate_primary_retrieval"](items, relevant, 5)

        self.assertEqual(result.core_metrics["mrr"], 0.0)
        self.assertEqual(result.core_metrics["recall@5"], 0.0)

    def test_top_k_sensitivity_reuses_evidence_label_evaluator(self):
        target = build_retrieved_item(
            "contains target evidence",
            {"file_path": "target.md", "chunk_index": 0},
        )
        per_question_results = [{
            "analysis_retrieved_items": [target],
            "relevant_sources": [
                RelevantSource(file_path="target.md", text="target evidence")
            ],
        }]
        namespace = _load_notebook_functions(
            {"compute_metrics_at_k"},
            {
                "evaluate_retrieval_case": evaluate_retrieval_case,
                "mean": mean,
                "per_question_results": per_question_results,
            },
        )

        metrics = namespace["compute_metrics_at_k"](1)

        self.assertEqual(metrics["recall@1"], 1.0)
        self.assertEqual(metrics["precision@1"], 1.0)
        self.assertEqual(metrics["ndcg@1"], 1.0)
        self.assertEqual(metrics["irrelevant_rate@1"], 0.0)

    def test_provenance_and_comparison_guards_cover_all_invariants(self):
        namespace = _load_notebook_functions(
            {
                "_sha256_file",
                "_settings_fingerprint",
                "_build_notebook_provenance",
                "_normalize_per_question",
                "_comparison_rejection_reasons",
            },
            {
                "Any": Any,
                "Path": Path,
                "ROOT_DIR": ROOT_DIR,
                "hashlib": hashlib,
                "json": json,
            },
        )
        namespace["_run_git_command"] = (
            lambda *args: "abc123" if args == ("rev-parse", "HEAD") else ""
        )
        snapshot = {
            "schema_version": "retrieval-settings-v1",
            "pipeline_fingerprint": "pipeline:v1",
            "top_k": 5,
        }

        with tempfile.TemporaryDirectory() as directory:
            dataset_path = Path(directory) / "golden.jsonl"
            dataset_path.write_text('{"id":"q1"}\n', encoding="utf-8")
            provenance = namespace["_build_notebook_provenance"](
                dataset_path,
                snapshot,
            )

        self.assertEqual(
            provenance["dataset_sha256"],
            hashlib.sha256(b'{"id":"q1"}\n').hexdigest(),
        )
        self.assertEqual(provenance["git_sha"], "abc123")
        self.assertFalse(provenance["git_dirty"])
        self.assertEqual(
            provenance["settings_fingerprint"],
            namespace["_settings_fingerprint"](snapshot),
        )

        report = {
            "report_schema": "retrieval-eval-v1",
            "metric_semantics_version": "evidence-label-v2",
            "mode": "live",
            "top_k": 5,
            "settings_snapshot": snapshot,
            "provenance": provenance,
        }
        expected = {
            "dataset_sha256": provenance["dataset_sha256"],
            "mode": "live",
            "top_k": 5,
            "pipeline_fingerprint": "pipeline:v1",
        }
        reject = namespace["_comparison_rejection_reasons"]
        self.assertEqual(reject(report, expected), [])

        mutations = [
            ("dataset", lambda item: item["provenance"].update(dataset_sha256="other")),
            ("mode", lambda item: item.update(mode="demo")),
            ("top-k", lambda item: item.update(top_k=10)),
            (
                "pipeline fingerprint",
                lambda item: item["settings_snapshot"].update(
                    pipeline_fingerprint="pipeline:v2"
                ),
            ),
        ]
        for expected_reason, mutate in mutations:
            candidate = copy.deepcopy(report)
            mutate(candidate)
            reasons = reject(candidate, expected)
            with self.subTest(reason=expected_reason):
                self.assertTrue(
                    any(expected_reason in reason for reason in reasons),
                    reasons,
                )

        cli_report = {
            "questions": [{
                "id": "q1",
                "question": "What?",
                "evaluation": {
                    "core_metrics": {"recall@5": 1.0},
                    "context_quality": {"irrelevant_rate@5": 0.0},
                },
            }]
        }
        normalized = namespace["_normalize_per_question"](cli_report)
        self.assertEqual(normalized[0]["id"], "q1")
        self.assertEqual(normalized[0]["core_metrics"]["recall@5"], 1.0)


if __name__ == "__main__":
    unittest.main()

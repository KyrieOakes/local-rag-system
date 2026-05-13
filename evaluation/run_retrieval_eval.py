from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings
from app.rag.query_processor import process_query
from app.rag.retriever import retrieve_relevant_documents
from evaluation.retrieval_metrics.evaluator import evaluate_retrieval_case
from evaluation.retrieval_metrics.matching import (
    build_retrieved_item,
    relevant_source_from_dict,
)


def main() -> None:
    args = _parse_args()
    examples = _load_jsonl(args.dataset)

    per_question = []
    for example in examples:
        question = example["question"]
        retrieval_query = process_query(question)["rewritten_query"] if args.use_query_processor else question
        retrieved_results = retrieve_relevant_documents(retrieval_query, top_k=args.top_k)

        retrieved_items = [
            build_retrieved_item(
                content=document.page_content,
                metadata=document.metadata,
                score=float(score) if score is not None else None,
            )
            for document, score in retrieved_results
        ]
        relevant_sources = [
            relevant_source_from_dict(item)
            for item in example.get("relevant_sources", [])
        ]
        evaluation = evaluate_retrieval_case(retrieved_items, relevant_sources, args.top_k)

        per_question.append({
            "id": example.get("id"),
            "question": question,
            "retrieval_query": retrieval_query,
            "evaluation": evaluation.to_dict(),
            "retrieved": [
                {
                    "rank": rank,
                    "id": item.id,
                    "score": item.score,
                    "file_path": item.metadata.get("file_path"),
                    "source": item.metadata.get("source"),
                    "file_name": item.metadata.get("file_name"),
                    "chunk_index": item.metadata.get("chunk_index"),
                    "content_preview": item.content[:240],
                }
                for rank, item in enumerate(retrieved_items, start=1)
            ],
        })

    report = _build_report(args, per_question)
    output_path = _write_report(report, args.output_dir, args.experiment_name)
    print(f"Wrote retrieval evaluation report: {output_path}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run retrieval metrics against a golden JSONL dataset.")
    parser.add_argument("--dataset", required=True, help="Path to golden retrieval JSONL dataset.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of retrieval results to evaluate.")
    parser.add_argument("--experiment-name", required=True, help="Name for this chunking/retrieval experiment.")
    parser.add_argument("--output-dir", default="evaluation/results", help="Directory for JSON reports.")
    parser.add_argument(
        "--use-query-processor",
        action="store_true",
        help="Evaluate production query rewriting before vector retrieval.",
    )
    return parser.parse_args()


def _load_jsonl(path: str) -> list[dict[str, Any]]:
    dataset_path = Path(path)
    records = []
    with dataset_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if "question" not in record:
                raise ValueError(f"{dataset_path}:{line_number} is missing required field: question")
            records.append(record)
    return records


def _build_report(args: argparse.Namespace, per_question: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate = _aggregate_evaluations(per_question)

    return {
        "report_schema": "retrieval-eval-v1",
        "experiment_name": args.experiment_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "evaluation_layer": "retrieval",
        "dataset": args.dataset,
        "top_k": args.top_k,
        "use_query_processor": args.use_query_processor,
        "metric_groups": {
            "core_metrics": ["recall@k", "precision@k", "mrr", "ndcg@k"],
            "context_quality": ["context_redundancy@k", "irrelevant_rate@k", "duplicate_rate@k"],
        },
        "settings_snapshot": {
            "qdrant_collection": settings.qdrant_collection,
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "embedding_model": settings.embedding_model,
        },
        "aggregate": aggregate,
        "questions": per_question,
    }


def _aggregate_evaluations(per_question: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    if not per_question:
        return {"core_metrics": {}, "context_quality": {}}

    first_evaluation = per_question[0]["evaluation"]
    aggregate = {}
    for group_name in ("core_metrics", "context_quality"):
        metric_names = first_evaluation[group_name].keys()
        aggregate[group_name] = {
            metric_name: mean(item["evaluation"][group_name][metric_name] for item in per_question)
            for metric_name in metric_names
        }
    return aggregate


def _write_report(report: dict[str, Any], output_dir: str, experiment_name: str) -> Path:
    safe_name = "".join(char if char.isalnum() or char in "-_" else "_" for char in experiment_name)
    output_path = Path(output_dir) / f"{safe_name}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return output_path


if __name__ == "__main__":
    main()

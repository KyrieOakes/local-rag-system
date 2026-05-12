import json
import logging
from datetime import datetime
from pathlib import Path

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

HISTORY_DIR = Path("logs/history")
JSONL_PATH = HISTORY_DIR / "rag_queries.jsonl"

CONTENT_PREVIEW_LENGTH = 200


def _truncate(text: str, max_len: int = CONTENT_PREVIEW_LENGTH) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text


def log_rag_query(
    question: str,
    rewritten_query: str,
    intent: str,
    retrieved_results: list[tuple[Document, float]],
    answer: str,
    top_k: int,
) -> None:
    """Log a RAG query to JSONL (full detail) and terminal (brief summary)."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Build retrieved chunk entries ──
    chunks = []
    for rank, (doc, score) in enumerate(retrieved_results, start=1):
        meta = doc.metadata
        chunks.append({
            "rank": rank,
            "content_preview": _truncate(doc.page_content),
            "file_name": meta.get("file_name", meta.get("source", "unknown")),
            "file_path": meta.get("file_path", ""),
            "chunk_index": meta.get("chunk_index", -1),
            "score": round(score, 4) if score is not None else None,
        })

    record = {
        "timestamp": timestamp,
        "question": question,
        "rewritten_query": rewritten_query,
        "intent": intent,
        "top_k": top_k,
        "retrieved_chunks": chunks,
        "answer": answer,
    }

    # ── Terminal output (brief) ──
    top_file = chunks[0]["file_name"] if chunks else "N/A"
    top_score = chunks[0]["score"] if chunks else 0
    logger.info(
        "[QUERY] %s | intent=%s | %d chunks | top: %s (%.3f) | answer: %s",
        timestamp,
        intent,
        len(chunks),
        top_file,
        top_score,
        _truncate(answer, 120),
    )

    # ── JSONL persistent log ──
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    with open(JSONL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

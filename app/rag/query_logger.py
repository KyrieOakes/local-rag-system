"""
RAG 查询日志模块。

每次 RAG 查询完成后调用 log_rag_query()，执行：
1. 终端输出：一行简洁的日志摘要（时间、意图、命中数、top 文件、答案预览）
2. JSONL 持久化：将完整查询轨迹写入 logs/history/rag_queries.jsonl，
   包含问题、改写后的查询、意图、检索结果（排名+内容预览+评分）、LLM 答案

用于调试、分析和回归测试。
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Mapping

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

HISTORY_DIR = Path("logs/history")
JSONL_PATH = HISTORY_DIR / "rag_queries.jsonl"

CONTENT_PREVIEW_LENGTH = 200
_jsonl_write_lock = threading.Lock()


def _truncate(text: str, max_len: int = CONTENT_PREVIEW_LENGTH) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text


def log_rag_query(
    question: str,
    rewritten_query: str,
    intent: str,
    retrieved_results: list[tuple[Document, float]],
    answer: str,
    top_k: int,
    *,
    conversation_id: str | None = None,
    routing: str | None = None,
    stage_timings: Mapping[str, float] | None = None,
    turn_id: str | None = None,
) -> None:
    """Log a RAG query to JSONL (full detail) and terminal (brief summary).

    Optional trace fields are keyword-only so existing callers using the
    original six-argument signature remain compatible. ``stage_timings`` is
    expressed in seconds and serialized as milliseconds.
    """
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
    if conversation_id is not None:
        record["conversation_id"] = conversation_id
    if routing is not None:
        record["routing"] = routing
    if turn_id is not None:
        record["turn_id"] = turn_id
    if stage_timings is not None:
        record["stage_timings_ms"] = {
            stage: round(float(elapsed) * 1000, 3)
            for stage, elapsed in stage_timings.items()
        }

    # ── Terminal output (brief) ──
    top_file = chunks[0]["file_name"] if chunks else "N/A"
    top_score = chunks[0]["score"] if chunks else 0.0
    top_score = top_score if top_score is not None else 0.0
    logger.info(
        "[QUERY] %s | conversation=%s | routing=%s | intent=%s | "
        "%d chunks | top: %s (%.3f) | answer: %s",
        timestamp,
        conversation_id or "N/A",
        routing or "N/A",
        intent,
        len(chunks),
        top_file,
        top_score,
        _truncate(answer, 120),
    )

    # ── JSONL persistent log ──
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _jsonl_write_lock:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        with open(JSONL_PATH, "a", encoding="utf-8") as f:
            f.write(line)

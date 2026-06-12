"""
RAG 查询服务层（核心编排 — 含 RAG 路由门控、会话上下文、Rerank 精排）。

query_rag() 编排完整的 RAG 查询流水线：
STEP 1 — 接收用户输入（在 API 层完成）
STEP 2 — 查询预处理 + RAG 路由门控（query_processor）
  - Layer 0: 关键词预过滤（问候语等，零 LLM 调用）
  - Layer 1: LLM 统一路由：决定是否需要检索 + 意图检测 + 改写/直接回答
  - 分流：needs_rag=False → 跳过 STEP 3，直接返回 LLM 回答
STEP 3 — 向量检索（仅 needs_rag=True 时执行）
  - 若 rerank 启用：检索 reranker_candidate_top_n 条候选（如 20）
  - 若 rerank 禁用：检索 top_k 条（如 5）
STEP 3.5 — Rerank 精排（仅 reranker_type != "none" 时执行）
  - Cross-Encoder / HybridFusion 对候选重排序
  - 保留 reranker_final_top_k 条
STEP 4 — 构建提示词
STEP 5 — LLM 生成答案
STEP 6 — 组装响应 + 记录日志
"""

import asyncio
import json
import logging
import threading
import time
import uuid

from app.core.config import settings
from app.rag.chain import generate_answer, generate_answer_stream
from app.rag.conversation_store import get_conversation_store
from app.rag.query_processor import process_query
from app.rag.query_logger import log_rag_query
from app.rag.reranker import get_reranker
from app.rag.retriever import retrieve_relevant_documents
from app.schemas.rag import QueryResponse, SourceChunk

logger = logging.getLogger(__name__)


def _save_exchange_safe(
    conversation_id: str,
    user_message: str,
    assistant_message: str,
    sources: list,
    routing: str,
):
    """Best-effort conversation persistence — never raises."""
    try:
        store = get_conversation_store()
        sources_raw = [s.model_dump() if hasattr(s, "model_dump") else s for s in sources]
        store.save_exchange(
            conversation_id=conversation_id,
            user_message=user_message,
            assistant_message=assistant_message,
            sources=sources_raw,
            routing=routing,
        )
    except Exception:
        logger.exception("Failed to persist conversation %s", conversation_id)


def _build_sources(retrieved_results: list) -> list[SourceChunk]:
    """Build SourceChunk list from retrieval results."""
    return [
        SourceChunk(
            content=document.page_content,
            source=document.metadata.get("source"),
            file_name=document.metadata.get("file_name"),
            file_path=document.metadata.get("file_path"),
            chunk_index=document.metadata.get("chunk_index"),
            page=document.metadata.get("page"),
            score=float(score) if score is not None else None,
        )
        for document, score in retrieved_results
    ]


def query_rag(
    question: str,
    top_k: int = 5,
    conversation_id: str | None = None,
    history: list | None = None,
    force_rag: bool = False,
) -> QueryResponse:
    history = history or []
    conversation_id = conversation_id or uuid.uuid4().hex[:12]

    # STEP 2 — Query processing + RAG routing gate
    step2_start = time.perf_counter()
    logger.info("[RAG][STEP 2] Query processing + routing 开始")
    processed = process_query(question, history=history)

    needs_rag = processed["needs_rag"] or force_rag
    routing = "rag" if needs_rag else ("greeting" if processed["intent"] == "chitchat" else "direct")

    logger.info(
        "[RAG][STEP 2] Query processing 完成，耗时 %.3fs, needs_rag=%s, intent=%s, routing=%s",
        time.perf_counter() - step2_start,
        needs_rag,
        processed["intent"],
        routing,
    )

    # Branch: non-RAG path — return direct answer immediately
    if not needs_rag:
        answer = processed.get("direct_answer") or "I'm not sure how to help with that."
        response = QueryResponse(
            question=question,
            answer=answer,
            sources=[],
            conversation_id=conversation_id,
            routing=routing,
        )
        # Async logging (non-blocking)
        threading.Thread(
            target=log_rag_query,
            args=(question, processed.get("rewritten_query", question),
                  processed["intent"], [], answer, top_k),
            daemon=True,
        ).start()
        # Persist conversation (non-blocking, best-effort)
        threading.Thread(
            target=_save_exchange_safe,
            args=(conversation_id, question, answer, [], routing),
            daemon=True,
        ).start()
        return response

    # RAG path — full pipeline
    retrieval_query = processed["rewritten_query"] or question

    # Decide retrieval size: wider fetch for rerank, narrow otherwise
    reranker_enabled = settings.reranker_type.lower() not in ("none", "")
    retrieval_k = settings.reranker_candidate_top_n if reranker_enabled else top_k

    # STEP 3 — Vector retrieval
    step3_start = time.perf_counter()
    logger.info("[RAG][STEP 3] 向量检索开始 (retrieval_k=%d, reranker=%s)", retrieval_k, settings.reranker_type)
    retrieved_results = retrieve_relevant_documents(
        question=retrieval_query,
        top_k=retrieval_k,
    )
    step3_elapsed = time.perf_counter() - step3_start
    logger.info("[RAG][STEP 3] 向量检索完成，命中 %d 条，耗时 %.3fs", len(retrieved_results), step3_elapsed)

    # STEP 3.5 — Rerank (only when enabled and candidates > final top_k)
    rerank_elapsed = 0.0
    if reranker_enabled and len(retrieved_results) > top_k:
        step35_start = time.perf_counter()
        logger.info("[RAG][STEP 3.5] Rerank 开始")
        reranker = get_reranker()
        documents_for_rerank = [doc for doc, _score in retrieved_results]
        retrieved_results = reranker.rerank(
            query=retrieval_query,
            documents=documents_for_rerank,
            top_k=top_k,
        )
        rerank_elapsed = time.perf_counter() - step35_start
        logger.info("[RAG][STEP 3.5] Rerank 完成，保留 %d 条，耗时 %.3fs", len(retrieved_results), rerank_elapsed)

    documents = [document for document, _score in retrieved_results]

    # STEP 4+5 — Generate answer
    answer = generate_answer(
        question=question,
        documents=documents,
        history=history,
    )

    # STEP 6 — Assemble response
    step6_start = time.perf_counter()
    logger.info("[RAG][STEP 6] 返回结果开始")

    sources = _build_sources(retrieved_results)

    response = QueryResponse(
        question=question,
        answer=answer,
        sources=sources,
        conversation_id=conversation_id,
        routing=routing,
    )
    logger.info("[RAG][STEP 6] 返回结果完成，耗时 %.3fs", time.perf_counter() - step6_start)

    # Async logging (non-blocking)
    threading.Thread(
        target=log_rag_query,
        args=(question, retrieval_query, processed["intent"],
              retrieved_results, answer, top_k),
        daemon=True,
    ).start()

    # Persist conversation (non-blocking, best-effort)
    threading.Thread(
        target=_save_exchange_safe,
        args=(conversation_id, question, answer, sources, routing),
        daemon=True,
    ).start()

    return response


def _sse_event(event: str, data: dict | str) -> str:
    """Format a Server-Sent Event line. All data is JSON-encoded for consistency."""
    if isinstance(data, str):
        payload = json.dumps(data, ensure_ascii=False)
    else:
        payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


async def query_rag_stream(
    question: str,
    top_k: int = 5,
    conversation_id: str | None = None,
    history: list | None = None,
    force_rag: bool = False,
):
    """Async generator that yields SSE-formatted events for streaming RAG responses."""
    history = history or []
    conversation_id = conversation_id or uuid.uuid4().hex[:12]

    # STEP 2 — Query processing + routing
    processed = process_query(question, history=history)
    needs_rag = processed["needs_rag"] or force_rag
    routing = "rag" if needs_rag else ("greeting" if processed["intent"] == "chitchat" else "direct")

    # Yield routing event
    yield _sse_event("routing", {"routing": routing, "conversation_id": conversation_id})

    # Non-RAG path — stream direct answer word-by-word for typing effect
    if not needs_rag:
        answer = processed.get("direct_answer") or "I'm not sure how to help with that."
        yield _sse_event("status", {"phase": "responding", "message": "Preparing response..."})
        # Stream answer word-by-word so the frontend renders progressively
        words = answer.split()
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            yield _sse_event("token", token)
            await asyncio.sleep(0)  # yield event loop so ASGI flushes each chunk
        yield _sse_event("sources", [])
        yield _sse_event("done", {})
        threading.Thread(
            target=log_rag_query,
            args=(question, processed.get("rewritten_query", question),
                  processed["intent"], [], answer, top_k),
            daemon=True,
        ).start()
        threading.Thread(
            target=_save_exchange_safe,
            args=(conversation_id, question, answer, [], routing),
            daemon=True,
        ).start()
        return

    # RAG path — retrieve and stream
    retrieval_query = processed["rewritten_query"] or question

    # Decide retrieval size: wider fetch for rerank, narrow otherwise
    reranker_enabled = settings.reranker_type.lower() not in ("none", "")
    retrieval_k = settings.reranker_candidate_top_n if reranker_enabled else top_k

    yield _sse_event("status", {"phase": "searching", "message": "Searching documents..."})

    step3_start = time.perf_counter()
    logger.info("[RAG][STREAM][STEP 3] 向量检索开始 (retrieval_k=%d, reranker=%s)", retrieval_k, settings.reranker_type)
    retrieved_results = retrieve_relevant_documents(
        question=retrieval_query,
        top_k=retrieval_k,
    )
    step3_elapsed = time.perf_counter() - step3_start
    logger.info("[RAG][STREAM][STEP 3] 向量检索完成，命中 %d 条，耗时 %.3fs", len(retrieved_results), step3_elapsed)

    # STEP 3.5 — Rerank
    rerank_elapsed = 0.0
    if reranker_enabled and len(retrieved_results) > top_k:
        yield _sse_event("status", {"phase": "reranking", "message": "Reranking results..."})
        step35_start = time.perf_counter()
        logger.info("[RAG][STREAM][STEP 3.5] Rerank 开始")
        reranker = get_reranker()
        documents_for_rerank = [doc for doc, _score in retrieved_results]
        retrieved_results = reranker.rerank(
            query=retrieval_query,
            documents=documents_for_rerank,
            top_k=top_k,
        )
        rerank_elapsed = time.perf_counter() - step35_start
        logger.info("[RAG][STREAM][STEP 3.5] Rerank 完成，保留 %d 条，耗时 %.3fs", len(retrieved_results), rerank_elapsed)

    documents = [document for document, _score in retrieved_results]
    sources = _build_sources(retrieved_results)

    yield _sse_event("status", {"phase": "generating", "message": "Generating answer..."})

    # Stream tokens from LLM
    full_answer = ""
    try:
        async for token in generate_answer_stream(
            question=question,
            documents=documents,
            history=history,
        ):
            full_answer += token
            yield _sse_event("token", token)
    except Exception as exc:
        logger.exception("LLM streaming failed mid-stream")
        yield _sse_event("error", {"message": f"Generation failed: {exc}", "phase": "generating"})
        full_answer += f"\n\n[Error: {exc}]"

    # Yield sources + done
    yield _sse_event("sources", [s.model_dump() for s in sources])
    yield _sse_event("done", {})

    # Async logging
    threading.Thread(
        target=log_rag_query,
        args=(question, retrieval_query, processed["intent"],
              retrieved_results, full_answer, top_k),
        daemon=True,
    ).start()

    # Persist conversation (non-blocking, best-effort)
    threading.Thread(
        target=_save_exchange_safe,
        args=(conversation_id, question, full_answer, sources, routing),
        daemon=True,
    ).start()

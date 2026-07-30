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
import time
import uuid

from app.core.background_tasks import submit_background_task
from app.core.config import settings
from app.rag.chain import generate_answer, generate_answer_stream
from app.rag.context_manager import (
    ContextWindowExceededError,
    compact_conversation_memory,
    prepare_generation_context,
    prepare_routing_memory,
    resolve_conversation_memory,
)
from app.rag.conversation_store import get_conversation_store
from app.rag.query_processor import QUERY_PROCESSING_SYSTEM_PROMPT, process_query
from app.rag.query_logger import log_rag_query
from app.rag.reranker import build_rerank_candidates, get_reranker
from app.rag.retriever import retrieve_relevant_documents
from app.schemas.rag import QueryResponse, SourceChunk

logger = logging.getLogger(__name__)

_STREAM_ERROR_MESSAGES = {
    "context": "Unable to prepare conversation context.",
    "routing": "Unable to route the request.",
    "retrieval": "Unable to retrieve relevant documents.",
    "rerank": "Unable to rerank retrieved documents.",
    "generation": "Unable to generate the answer.",
}
DIRECT_STREAM_CHUNK_CHARS = 12


def _save_exchange_safe(
    conversation_id: str,
    user_message: str,
    assistant_message: str,
    sources: list,
    routing: str,
    turn_id: str | None = None,
):
    """Best-effort conversation persistence — never raises."""
    try:
        store = get_conversation_store()
        sources_raw = [s.model_dump() if hasattr(s, "model_dump") else s for s in sources]
        saved = store.save_exchange(
            conversation_id=conversation_id,
            user_message=user_message,
            assistant_message=assistant_message,
            sources=sources_raw,
            routing=routing,
            turn_id=turn_id,
        )
        if saved:
            compact_conversation_memory(conversation_id, store=store)
    except Exception:
        logger.exception("Failed to persist conversation %s", conversation_id)


def _rerank_results(
    retrieval_query: str,
    retrieved_results: list,
    top_k: int,
) -> list:
    """Run the configured reranker behind one stable service boundary."""
    reranker = get_reranker()
    candidates = build_rerank_candidates(retrieved_results)
    return reranker.rerank(
        query=retrieval_query,
        candidates=candidates,
        top_k=top_k,
    )


def _schedule_completed_query(
    *,
    conversation_id: str,
    turn_id: str,
    question: str,
    answer: str,
    sources: list,
    routing: str,
    rewritten_query: str,
    intent: str,
    retrieved_results: list,
    top_k: int,
    stage_timings: dict[str, float],
) -> None:
    """Queue persistence and tracing only after an answer fully completes."""
    persistence_future = submit_background_task(
        _save_exchange_safe,
        conversation_id,
        question,
        answer,
        sources,
        routing,
        turn_id,
    )
    logging_future = submit_background_task(
        log_rag_query,
        question,
        rewritten_query,
        intent,
        retrieved_results,
        answer,
        top_k,
        conversation_id=conversation_id,
        routing=routing,
        stage_timings=stage_timings,
        turn_id=turn_id,
    )
    if persistence_future is None:
        logger.error(
            "Conversation persistence was not queued for conversation=%s turn=%s",
            conversation_id,
            turn_id,
        )
    if logging_future is None:
        logger.error(
            "Query trace was not queued for conversation=%s turn=%s",
            conversation_id,
            turn_id,
        )


def _stream_error(
    phase: str,
    conversation_id: str,
) -> str:
    """Build the stable SSE error payload shared by all stream phases."""
    return _sse_event(
        "error",
        {
            "message": _STREAM_ERROR_MESSAGES.get(
                phase,
                "Unable to complete the request.",
            ),
            "phase": phase,
            "conversation_id": conversation_id,
        },
    )


def _stream_context_limit_error(
    error: ContextWindowExceededError,
    conversation_id: str,
) -> str:
    """Expose the deliberate, user-actionable context limit error only."""
    return _sse_event(
        "error",
        {
            "message": str(error),
            "phase": "context",
            "conversation_id": conversation_id,
        },
    )


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


def _iter_text_chunks(
    text: str,
    chunk_chars: int = DIRECT_STREAM_CHUNK_CHARS,
):
    """Yield small Unicode slices without dropping or inventing whitespace."""
    if chunk_chars < 1:
        raise ValueError("chunk_chars must be at least 1")
    for start in range(0, len(text), chunk_chars):
        yield text[start:start + chunk_chars]


def query_rag(
    question: str,
    top_k: int = 5,
    conversation_id: str | None = None,
    history: list | None = None,
    force_rag: bool = False,
    turn_id: str | None = None,
) -> QueryResponse:
    total_start = time.perf_counter()
    stage_timings: dict[str, float] = {}
    history = history or []
    conversation_id = conversation_id or uuid.uuid4().hex[:12]
    turn_id = turn_id or uuid.uuid4().hex

    context_start = time.perf_counter()
    memory = resolve_conversation_memory(conversation_id, history)
    routing_memory = prepare_routing_memory(
        question,
        memory,
        QUERY_PROCESSING_SYSTEM_PROMPT,
    )
    stage_timings["context"] = time.perf_counter() - context_start

    # STEP 2 — Query processing + RAG routing gate
    step2_start = time.perf_counter()
    logger.info("[RAG][STEP 2] Query processing + routing 开始")
    processed = process_query(
        question,
        history=routing_memory.messages,
        conversation_summary=routing_memory.summary,
    )
    stage_timings["routing"] = time.perf_counter() - step2_start

    needs_rag = processed["needs_rag"] or force_rag
    routing = "rag" if needs_rag else (
        "greeting" if processed["intent"] == "chitchat" else "direct"
    )

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
        stage_timings["total"] = time.perf_counter() - total_start
        _schedule_completed_query(
            conversation_id=conversation_id,
            turn_id=turn_id,
            question=question,
            answer=answer,
            sources=[],
            routing=routing,
            rewritten_query=processed.get("rewritten_query") or question,
            intent=processed["intent"],
            retrieved_results=[],
            top_k=top_k,
            stage_timings=stage_timings,
        )
        return response

    # RAG path — full pipeline
    retrieval_query = processed["rewritten_query"] or question

    # Decide retrieval size: wider fetch for rerank, narrow otherwise
    reranker_enabled = settings.reranker_type.lower() not in ("none", "")
    final_top_k = settings.reranker_final_top_k if reranker_enabled else top_k
    retrieval_k = (
        settings.reranker_candidate_top_n
        if reranker_enabled
        else final_top_k
    )

    # STEP 3 — Vector retrieval
    step3_start = time.perf_counter()
    logger.info("[RAG][STEP 3] 向量检索开始 (retrieval_k=%d, reranker=%s)", retrieval_k, settings.reranker_type)
    retrieved_results = retrieve_relevant_documents(
        question=retrieval_query,
        top_k=retrieval_k,
    )
    step3_elapsed = time.perf_counter() - step3_start
    stage_timings["retrieval"] = step3_elapsed
    logger.info("[RAG][STEP 3] 向量检索完成，命中 %d 条，耗时 %.3fs", len(retrieved_results), step3_elapsed)

    # STEP 3.5 — Rerank (only when enabled and candidates > final top_k)
    rerank_elapsed = 0.0
    if reranker_enabled and len(retrieved_results) > final_top_k:
        step35_start = time.perf_counter()
        logger.info("[RAG][STEP 3.5] Rerank 开始")
        retrieved_results = _rerank_results(
            retrieval_query,
            retrieved_results,
            final_top_k,
        )
        rerank_elapsed = time.perf_counter() - step35_start
        stage_timings["rerank"] = rerank_elapsed
        logger.info("[RAG][STEP 3.5] Rerank 完成，保留 %d 条，耗时 %.3fs", len(retrieved_results), rerank_elapsed)

    documents = [document for document, _score in retrieved_results]
    generation_context_start = time.perf_counter()
    context_plan = prepare_generation_context(
        question=question,
        memory=memory,
        documents=documents,
    )
    stage_timings["generation_context"] = (
        time.perf_counter() - generation_context_start
    )
    retrieved_results = retrieved_results[:context_plan.included_document_count]

    # STEP 4+5 — Generate answer
    generation_start = time.perf_counter()
    answer = generate_answer(
        question=question,
        documents=context_plan.documents,
        history=context_plan.history,
        conversation_summary=context_plan.summary,
    )
    stage_timings["generation"] = time.perf_counter() - generation_start

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

    stage_timings["total"] = time.perf_counter() - total_start
    _schedule_completed_query(
        conversation_id=conversation_id,
        turn_id=turn_id,
        question=question,
        answer=answer,
        sources=sources,
        routing=routing,
        rewritten_query=retrieval_query,
        intent=processed["intent"],
        retrieved_results=retrieved_results,
        top_k=final_top_k,
        stage_timings=stage_timings,
    )

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
    turn_id: str | None = None,
):
    """Async generator that yields SSE-formatted events for streaming RAG responses."""
    total_start = time.perf_counter()
    stage_timings: dict[str, float] = {}
    history = history or []
    conversation_id = conversation_id or uuid.uuid4().hex[:12]
    turn_id = turn_id or uuid.uuid4().hex

    # Context restoration reads SQLite and tokenizes text, so keep it off the
    # event loop along with the explicitly blocking model/retrieval phases.
    context_start = time.perf_counter()
    try:
        memory = await asyncio.to_thread(
            resolve_conversation_memory,
            conversation_id,
            history,
        )
        routing_memory = await asyncio.to_thread(
            prepare_routing_memory,
            question,
            memory,
            QUERY_PROCESSING_SYSTEM_PROMPT,
        )
        stage_timings["context"] = time.perf_counter() - context_start
    except asyncio.CancelledError:
        logger.info(
            "SSE request cancelled during context phase conversation=%s",
            conversation_id,
        )
        raise
    except ContextWindowExceededError as exc:
        yield _stream_context_limit_error(exc, conversation_id)
        yield _sse_event("done", {})
        return
    except Exception as exc:
        logger.exception(
            "SSE context preparation failed conversation=%s",
            conversation_id,
        )
        yield _stream_error("context", conversation_id)
        yield _sse_event("done", {})
        return

    # STEP 2 — Query processing + routing
    routing_start = time.perf_counter()
    try:
        processed = await asyncio.to_thread(
            process_query,
            question,
            history=routing_memory.messages,
            conversation_summary=routing_memory.summary,
        )
        stage_timings["routing"] = time.perf_counter() - routing_start
    except asyncio.CancelledError:
        logger.info(
            "SSE request cancelled during routing phase conversation=%s",
            conversation_id,
        )
        raise
    except Exception as exc:
        logger.exception("SSE routing failed conversation=%s", conversation_id)
        yield _stream_error("routing", conversation_id)
        yield _sse_event("done", {})
        return

    try:
        if not isinstance(processed, dict):
            raise TypeError("routing result must be a dictionary")
        needs_rag = processed["needs_rag"] or force_rag
        intent = processed.get("intent", "unknown")
        routing = "rag" if needs_rag else (
            "greeting" if intent == "chitchat" else "direct"
        )
    except Exception as exc:
        logger.exception(
            "SSE routing result was invalid conversation=%s",
            conversation_id,
        )
        yield _stream_error("routing", conversation_id)
        yield _sse_event("done", {})
        return

    # Yield routing event
    yield _sse_event("routing", {"routing": routing, "conversation_id": conversation_id})

    # Non-RAG path — stream direct answer in small, whitespace-preserving chunks
    if not needs_rag:
        answer = processed.get("direct_answer") or "I'm not sure how to help with that."
        yield _sse_event("status", {"phase": "responding", "message": "Preparing response..."})

        try:
            # Preserve newlines, repeated spaces, and languages without spaces.
            for token in _iter_text_chunks(answer):
                yield _sse_event("token", token)
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            logger.info(
                "SSE request cancelled while responding conversation=%s",
                conversation_id,
            )
            raise

        stage_timings["total"] = time.perf_counter() - total_start
        _schedule_completed_query(
            conversation_id=conversation_id,
            turn_id=turn_id,
            question=question,
            answer=answer,
            sources=[],
            routing=routing,
            rewritten_query=processed.get("rewritten_query") or question,
            intent=intent,
            retrieved_results=[],
            top_k=top_k,
            stage_timings=stage_timings,
        )
        yield _sse_event("sources", [])
        yield _sse_event("done", {})
        return

    # RAG path — retrieve and stream
    retrieval_query = processed.get("rewritten_query") or question

    # Decide retrieval size: wider fetch for rerank, narrow otherwise
    reranker_enabled = settings.reranker_type.lower() not in ("none", "")
    final_top_k = settings.reranker_final_top_k if reranker_enabled else top_k
    retrieval_k = (
        settings.reranker_candidate_top_n
        if reranker_enabled
        else final_top_k
    )

    yield _sse_event("status", {"phase": "searching", "message": "Searching documents..."})

    step3_start = time.perf_counter()
    logger.info("[RAG][STREAM][STEP 3] 向量检索开始 (retrieval_k=%d, reranker=%s)", retrieval_k, settings.reranker_type)
    try:
        retrieved_results = await asyncio.to_thread(
            retrieve_relevant_documents,
            question=retrieval_query,
            top_k=retrieval_k,
        )
        retrieved_results = list(retrieved_results)
    except asyncio.CancelledError:
        logger.info(
            "SSE request cancelled during retrieval conversation=%s",
            conversation_id,
        )
        raise
    except Exception as exc:
        logger.exception("SSE retrieval failed conversation=%s", conversation_id)
        yield _stream_error("retrieval", conversation_id)
        yield _sse_event("done", {})
        return

    step3_elapsed = time.perf_counter() - step3_start
    stage_timings["retrieval"] = step3_elapsed
    logger.info("[RAG][STREAM][STEP 3] 向量检索完成，命中 %d 条，耗时 %.3fs", len(retrieved_results), step3_elapsed)

    # STEP 3.5 — Rerank
    rerank_elapsed = 0.0
    if reranker_enabled and len(retrieved_results) > final_top_k:
        yield _sse_event("status", {"phase": "reranking", "message": "Reranking results..."})
        step35_start = time.perf_counter()
        logger.info("[RAG][STREAM][STEP 3.5] Rerank 开始")
        try:
            retrieved_results = await asyncio.to_thread(
                _rerank_results,
                retrieval_query,
                retrieved_results,
                final_top_k,
            )
            retrieved_results = list(retrieved_results)
        except asyncio.CancelledError:
            logger.info(
                "SSE request cancelled during rerank conversation=%s",
                conversation_id,
            )
            raise
        except Exception as exc:
            logger.exception("SSE rerank failed conversation=%s", conversation_id)
            yield _stream_error("rerank", conversation_id)
            yield _sse_event("done", {})
            return

        rerank_elapsed = time.perf_counter() - step35_start
        stage_timings["rerank"] = rerank_elapsed
        logger.info("[RAG][STREAM][STEP 3.5] Rerank 完成，保留 %d 条，耗时 %.3fs", len(retrieved_results), rerank_elapsed)

    generation_context_start = time.perf_counter()
    try:
        documents = [document for document, _score in retrieved_results]
        context_plan = await asyncio.to_thread(
            prepare_generation_context,
            question=question,
            memory=memory,
            documents=documents,
        )
        stage_timings["generation_context"] = (
            time.perf_counter() - generation_context_start
        )
        retrieved_results = retrieved_results[
            :context_plan.included_document_count
        ]
        sources = _build_sources(retrieved_results)
    except asyncio.CancelledError:
        logger.info(
            "SSE request cancelled during generation context conversation=%s",
            conversation_id,
        )
        raise
    except ContextWindowExceededError as exc:
        yield _stream_context_limit_error(exc, conversation_id)
        yield _sse_event("done", {})
        return
    except Exception as exc:
        logger.exception(
            "SSE generation context failed conversation=%s",
            conversation_id,
        )
        yield _stream_error("context", conversation_id)
        yield _sse_event("done", {})
        return

    yield _sse_event("status", {"phase": "generating", "message": "Generating answer..."})

    # Stream tokens from LLM
    full_answer = ""
    generation_start = time.perf_counter()
    try:
        async for token in generate_answer_stream(
            question=question,
            documents=context_plan.documents,
            history=context_plan.history,
            conversation_summary=context_plan.summary,
        ):
            full_answer += token
            yield _sse_event("token", token)
    except asyncio.CancelledError:
        logger.info(
            "SSE request cancelled during generation conversation=%s",
            conversation_id,
        )
        raise
    except Exception as exc:
        logger.exception(
            "LLM streaming failed mid-stream conversation=%s",
            conversation_id,
        )
        yield _stream_error("generation", conversation_id)
        yield _sse_event("done", {})
        return

    stage_timings["generation"] = time.perf_counter() - generation_start
    stage_timings["total"] = time.perf_counter() - total_start
    _schedule_completed_query(
        conversation_id=conversation_id,
        turn_id=turn_id,
        question=question,
        answer=full_answer,
        sources=sources,
        routing=routing,
        rewritten_query=retrieval_query,
        intent=intent,
        retrieved_results=retrieved_results,
        top_k=final_top_k,
        stage_timings=stage_timings,
    )

    # Only successfully completed answers produce sources, persistence, and a
    # normal terminal event. Failed/cancelled streams never save partial text.
    yield _sse_event("sources", [s.model_dump() for s in sources])
    yield _sse_event("done", {})

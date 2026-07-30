"""
RAG 查询 API 路由模块。

提供两个端点：
- POST /rag/query — 标准 RAG 查询，返回完整 JSON 响应
- POST /rag/query/stream — SSE 流式 RAG 查询，逐 token 返回

两个端点共享相同的请求体，串联了查询处理→路由门控→向量检索→答案生成的完整流水线。
"""

import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.background_tasks import shutdown_background_tasks
from app.core.config import settings
from app.schemas.rag import QueryRequest, QueryResponse
from app.services.rag_service import query_rag, query_rag_stream
from app.rag.context_manager import ContextWindowExceededError


router = APIRouter(prefix="/rag", tags=["RAG"])
logger = logging.getLogger(__name__)


@router.on_event("shutdown")
def shutdown_rag_background_tasks() -> None:
    """Drain accepted query logging/persistence work during app shutdown."""
    shutdown_background_tasks(wait=True)


@router.post("/query", response_model=QueryResponse)
def rag_query(payload: QueryRequest, request: Request):
    try:
        step1_start = time.perf_counter()
        logger.info("[RAG][STEP 1] 用户输入接收开始")
        logger.info("[RAG][STEP 1] 用户输入接收完成，耗时 %.3fs", time.perf_counter() - step1_start)
        return query_rag(
            question=payload.question,
            top_k=settings.top_k,
            conversation_id=payload.conversation_id,
            history=payload.history,
            force_rag=payload.force_rag,
            turn_id=getattr(request.state, "request_id", None),
        )

    except ContextWindowExceededError as error:
        raise HTTPException(status_code=413, detail=str(error))
    except Exception:
        logger.exception(
            "Synchronous RAG query failed request_id=%s",
            getattr(request.state, "request_id", "unknown"),
        )
        raise HTTPException(status_code=500, detail="RAG query failed.")


@router.post("/query/stream")
async def rag_query_stream(payload: QueryRequest, request: Request):
    """Stream RAG response via Server-Sent Events.

    Events emitted:
    - routing: {routing, conversation_id}
    - status: {phase, message}         -- pipeline progress indicator
    - token: "<string>"                -- individual answer token (JSON-encoded)
    - sources: [...SourceChunk]
    - done: {}
    - error: {message, phase}          -- emitted on streaming failure
    """
    try:
        logger.info("[RAG][STREAM] 流式查询开始")
        return StreamingResponse(
            query_rag_stream(
                question=payload.question,
                top_k=settings.top_k,
                conversation_id=payload.conversation_id,
                history=payload.history,
                force_rag=payload.force_rag,
                turn_id=getattr(request.state, "request_id", None),
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception:
        logger.exception(
            "Failed to initialize streaming RAG response request_id=%s",
            getattr(request.state, "request_id", "unknown"),
        )
        raise HTTPException(status_code=500, detail="Streaming RAG query failed.")

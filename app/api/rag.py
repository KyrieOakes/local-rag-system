"""
RAG 查询 API 路由模块。

提供两个端点：
- POST /rag/query — 标准 RAG 查询，返回完整 JSON 响应
- POST /rag/query/stream — SSE 流式 RAG 查询，逐 token 返回

两个端点共享相同的请求体，串联了查询处理→路由门控→向量检索→答案生成的完整流水线。
"""

import logging
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.rag import QueryRequest, QueryResponse
from app.services.rag_service import query_rag, query_rag_stream


router = APIRouter(prefix="/rag", tags=["RAG"])
logger = logging.getLogger(__name__)


@router.post("/query", response_model=QueryResponse)
def rag_query(request: QueryRequest):
    try:
        step1_start = time.perf_counter()
        logger.info("[RAG][STEP 1] 用户输入接收开始")
        logger.info("[RAG][STEP 1] 用户输入接收完成，耗时 %.3fs", time.perf_counter() - step1_start)
        return query_rag(
            question=request.question,
            top_k=5,
            conversation_id=request.conversation_id,
            history=request.history,
            force_rag=request.force_rag,
        )

    except Exception as error:
        raise HTTPException(status_code=500, detail=f"RAG query failed: {error}")


@router.post("/query/stream")
async def rag_query_stream(request: QueryRequest):
    """Stream RAG response via Server-Sent Events.

    Events emitted:
    - routing: {routing, conversation_id}
    - token: <string token>
    - sources: [...SourceChunk]
    - done: {}
    """
    try:
        logger.info("[RAG][STREAM] 流式查询开始")
        return StreamingResponse(
            query_rag_stream(
                question=request.question,
                top_k=5,
                conversation_id=request.conversation_id,
                history=request.history,
                force_rag=request.force_rag,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Streaming RAG query failed: {error}")

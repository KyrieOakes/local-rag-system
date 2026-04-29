import logging
import time

from fastapi import APIRouter, HTTPException

from app.schemas.rag import QueryRequest, QueryResponse
from app.services.rag_service import query_rag


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
            top_k=request.top_k,
        )

    except Exception as error:
        raise HTTPException(status_code=500, detail=f"RAG query failed: {error}")

"""
RAG 查询 API 路由模块。

提供 POST /rag/query 端点，接收用户问题并返回：
- answer: LLM 基于检索到的文档块生成的回答
- sources: 检索到的文档块列表，包含内容、来源、相关性评分

这是整个 RAG 系统对外的核心接口，串联了查询处理→向量检索→答案生成→日志记录的完整流水线。
"""

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
            top_k=5,
        )

    except Exception as error:
        raise HTTPException(status_code=500, detail=f"RAG query failed: {error}")

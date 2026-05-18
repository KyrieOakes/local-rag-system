"""
RAG 查询服务层（核心编排）。

query_rag() 编排完整的 RAG 查询流水线，共 6 步：
STEP 1 — 接收用户输入（在 API 层完成）
STEP 2 — 查询预处理：意图检测 + 查询改写（query_processor）
STEP 3 — 向量检索：从 Qdrant 检索 top_k 个最相关文档块（retriever）
STEP 4 — 构建提示词（chain）
STEP 5 — LLM 生成答案（chain）
STEP 6 — 组装响应 + 记录日志（query_logger）

返回 QueryResponse，包含原始问题、生成的答案和检索到的来源列表。
"""

import logging
import time

from app.rag.chain import generate_answer
from app.rag.query_processor import process_query
from app.rag.query_logger import log_rag_query
from app.rag.retriever import retrieve_relevant_documents
from app.schemas.rag import QueryResponse, SourceChunk

logger = logging.getLogger(__name__)


def query_rag(question: str, top_k: int = 5) -> QueryResponse:
    step2_start = time.perf_counter()
    logger.info("[RAG][STEP 2] Query processing 开始")
    processed = process_query(question)
    retrieval_query = processed["rewritten_query"]
    logger.info(
        "[RAG][STEP 2] Query processing 完成，耗时 %.3fs, intent=%s",
        time.perf_counter() - step2_start,
        processed["intent"],
    )

    retrieved_results = retrieve_relevant_documents(
        question=retrieval_query,
        top_k=top_k,
    )

    documents = [document for document, _score in retrieved_results]

    answer = generate_answer(
        question=question,
        documents=documents,
    )

    step6_start = time.perf_counter()
    logger.info("[RAG][STEP 6] 返回结果开始")

    sources = [
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

    response = QueryResponse(
        question=question,
        answer=answer,
        sources=sources,
    )
    logger.info("[RAG][STEP 6] 返回结果完成，耗时 %.3fs", time.perf_counter() - step6_start)

    # Log full query trace to JSONL + brief summary to terminal
    log_rag_query(
        question=question,
        rewritten_query=retrieval_query,
        intent=processed["intent"],
        retrieved_results=retrieved_results,
        answer=answer,
        top_k=top_k,
    )

    return response

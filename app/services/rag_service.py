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

import logging
import time

from app.rag.chain import generate_answer
from app.rag.retriever import retrieve_relevant_documents
from app.schemas.rag import QueryResponse, SourceChunk

logger = logging.getLogger(__name__)

# 定义RAG查询函数，接受用户问题和可选的top_k参数，返回包含答案和相关来源信息的QueryResponse对象
def query_rag(question: str, top_k: int = 5) -> QueryResponse:
    retrieved_results = retrieve_relevant_documents(
        question=question,
        top_k=top_k,
    )

    # 从检索结果中提取文档列表，准备生成答案所需的上下文信息
    documents = [document for document, _score in retrieved_results]

    answer = generate_answer(
        question=question,
        documents=documents,
    )

    step6_start = time.perf_counter()
    logger.info("[RAG][STEP 6] 返回结果开始")

    # 将检索结果中的文档内容、来源和评分信息封装为SourceChunk对象列表，作为答案的来源信息
    sources = [
        SourceChunk(
            content=document.page_content,
            source=document.metadata.get("source"),
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

    return response

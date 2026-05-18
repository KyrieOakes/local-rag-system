"""
向量检索器模块（RAG 流水线第 3 步）。

retrieve_relevant_documents() 对用户查询（或改写后的查询）执行向量相似度搜索，
从 Qdrant 向量数据库中检索 top_k 个最相关的文档块。
返回 list[tuple[Document, float]]——每个元组包含文档对象和余弦相似度评分。

检索使用 Qdrant 的 similarity_search_with_score 方法，
结合嵌入模型将查询文本转为向量后在向量空间中搜索最近邻。
"""

import logging
import time

from langchain_core.documents import Document

from app.rag.vectorstore import get_vectorstore

logger = logging.getLogger(__name__)

# 从向量数据库中检索与问题相关的文档，返回文档和相似度评分的列表
def retrieve_relevant_documents(question: str, top_k: int = 5) -> list[tuple[Document, float]]:
    # 获取向量数据库实例
    vectorstore = get_vectorstore()

    # 使用相似度搜索方法检索相关文档，返回文档和相似度评分的列表
    step3_start = time.perf_counter()
    logger.info("[RAG][STEP 3] 向量检索开始")
    results = vectorstore.similarity_search_with_score(
        query=question,
        k=top_k,
    )
    logger.info("[RAG][STEP 3] 向量检索完成，命中 %s 条，耗时 %.3fs", len(results), time.perf_counter() - step3_start)

    return results
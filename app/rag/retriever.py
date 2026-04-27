from langchain_core.documents import Document

from app.rag.vectorstore import get_vectorstore

# 从向量数据库中检索与问题相关的文档，返回文档和相似度评分的列表
def retrieve_relevant_documents(question: str, top_k: int = 5) -> list[tuple[Document, float]]:
    # 获取向量数据库实例
    vectorstore = get_vectorstore()

    # 使用相似度搜索方法检索相关文档，返回文档和相似度评分的列表
    results = vectorstore.similarity_search_with_score(
        query=question,
        k=top_k,
    )

    return results
from langchain_qdrant import QdrantVectorStore

from app.core.config import settings
from app.rag.embeddings import get_embedding_model

# 获取现有的向量数据库实例，如果不存在则创建一个新的实例
def get_vectorstore() -> QdrantVectorStore:
    # 获取嵌入模型实例
    embedding_model = get_embedding_model()

    # 从现有的Qdrant集合中创建一个QdrantVectorStore实例，
    # 使用指定的嵌入模型、集合名称和URL连接到Qdrant数据库
    return QdrantVectorStore.from_existing_collection(
        embedding=embedding_model,
        collection_name=settings.qdrant_collection,
        url=settings.qdrant_url,
    )

# 从文档列表创建一个新的向量数据库实例，并将文档存储到Qdrant数据库中
def create_vectorstore_from_documents(documents):
    embedding_model = get_embedding_model()

    # 从文档列表创建一个新的QdrantVectorStore实例，并将文档存储到指定的Qdrant集合中，
    return QdrantVectorStore.from_documents(
        documents=documents,
        embedding=embedding_model,
        collection_name=settings.qdrant_collection,
        url=settings.qdrant_url,
        # 如果集合已经存在，则不强制重新创建，而是使用现有的集合来存储文档
        force_recreate=False,
    )
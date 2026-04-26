from app.rag.loader import load_document
from app.rag.splitter import split_documents
from app.rag.vectorstore import create_vectorstore_from_documents

# 处理文档的摄取过程，包括加载文档内容、分割文档内容和创建向量存储
def ingest_document(file_path: str, original_filename: str) -> dict:
    documents = load_document(file_path)

    # 将原始文件名和文件路径添加到每个Document对象的metadata中，方便后续查询和管理文档
    for document in documents:
        document.metadata["source"] = original_filename
        document.metadata["file_path"] = file_path

    # 将文档内容进行分割，返回分割后的Document对象列表，
    # 分割的方式根据设置的chunk_size和chunk_overlap以及定义的分隔符进行分割
    chunks = split_documents(documents)

    # 将分割后的文档内容创建向量存储，方便后续的相似度搜索和查询，
    # 向量存储的创建过程会将每个Document对象转换为向量表示，并存储在数据库中
    create_vectorstore_from_documents(chunks)

    return {
        "filename": original_filename,
        "file_path": file_path,
        "pages": len(documents),
        "chunks": len(chunks),
        "status": "indexed",    # 表示文档已经成功被索引和存储在向量数据库中，准备好进行查询和检索
    }
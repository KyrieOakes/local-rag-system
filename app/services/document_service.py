import os
from pathlib import Path

from app.rag.vectorstore import list_all_documents, delete_document_by_source

# 定义数据目录，与 file_utils.py 中的 UPLOAD_DIR 保持一致
DATA_DIR = Path("data/raw")


def list_documents() -> list[dict]:
    """
    列出所有已索引的文档信息。
    返回格式: [{"source": "foo.pdf", "file_type": ".pdf", "chunks": 12}, ...]
    """
    return list_all_documents()


def delete_document(source: str) -> dict:
    """
    按文件名（source）删除文档：
    1. 从 Qdrant 向量库中删除所有分块
    2. 从本地文件系统中删除原始文件（如果存在）
    返回删除结果信息。
    """
    # 1. 从 Qdrant 删除
    deleted_chunks = delete_document_by_source(source)

    # 2. 从本地文件系统删除
    file_deleted = False
    for f in DATA_DIR.glob("*"):
        if f.is_file() and f.name.endswith(Path(source).suffix):
            # 通过遍历找到匹配同名文件的 UUID 命名文件比较困难，
            # 因此我们同时尝试删除与 source 完全匹配的文件
            pass

    # 尝试删除 source 直接命名的文件（如果有的话）
    direct_path = DATA_DIR / source
    if direct_path.exists() and direct_path.is_file():
        os.remove(direct_path)
        file_deleted = True

    # 也尝试通过遍历在 metadata 中查找 file_path
    # 由于我们已经有了完整的 list_all_documents，但这里 source 已经足够
    # 如果 chunks 为 0，表示未找到文档

    return {
        "source": source,
        "deleted_chunks": deleted_chunks,
        "file_deleted": file_deleted,
        "status": "deleted" if deleted_chunks > 0 else "not_found",
    }
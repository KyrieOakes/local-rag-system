from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
from langchain_core.documents import Document

# 加载文档内容并返回Document对象列表
def load_document(file_path: str) -> list[Document]:
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        loader = PyPDFLoader(str(path))
        return loader.load()

    if suffix in [".txt", ".md", ".markdown"]:
        loader = TextLoader(str(path), encoding="utf-8")
        return loader.load()

    if suffix == ".docx":
        loader = Docx2txtLoader(str(path))
        return loader.load()

    # 如果文件类型不受支持，则抛出一个ValueError异常，提示用户文件类型不受支持
    raise ValueError(f"Unsupported file type: {suffix}")
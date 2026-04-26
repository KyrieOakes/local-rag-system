from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document

# 加载文档内容并返回Document对象列表
def load_document(file_path: str) -> list[Document]:
    path = Path(file_path)
    # 获取文件的后缀名，并将其转换为小写，以便进行文件类型判断
    suffix = path.suffix.lower()

    # 根据文件类型选择合适的加载器来加载文档内容，目前支持PDF、TXT和MD格式
    if suffix == ".pdf":
        loader = PyPDFLoader(str(path))
        return loader.load()

    if suffix in [".txt", ".md"]:
        loader = TextLoader(str(path), encoding="utf-8")
        return loader.load()

    # 如果文件类型不受支持，则抛出一个ValueError异常，提示用户文件类型不受支持
    raise ValueError(f"Unsupported file type: {suffix}")
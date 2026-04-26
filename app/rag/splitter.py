from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from app.core.config import settings

# 将文档内容进行分割，返回分割后的Document对象列表
def split_documents(documents: list[Document]) -> list[Document]:
    # 创建一个RecursiveCharacterTextSplitter实例
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        # 定义分割文本的分隔符列表，按照优先级从高到低进行分割，
        # 首先尝试使用双换行符进行分割，如果无法满足chunk_size的要求，
        # 则依次尝试使用单换行符、中文句号、英文句号、空格和最后的无分隔符进行分割
        separators=["\n\n", "\n", "。", ".", " ", ""],
    )

    return splitter.split_documents(documents)
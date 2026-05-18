"""
文档切分器模块。

根据文件类型采用不同的切分策略：
- Markdown 文件（.md / .markdown）：先用 MarkdownHeaderTextSplitter 按 H1/H2/H3
  标题层级切分（保留标题层级元数据），再用 RecursiveCharacterTextSplitter 对
  超过 chunk_size 的段落进一步切分
- 其他文件类型（.pdf / .txt / .docx）：直接使用 RecursiveCharacterTextSplitter 切分，
  分隔符优先级为：\n\n → \n → 。 → . → 空格 → 字符

chunk_size 和 chunk_overlap 从 settings 读取（默认 800/120）。
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from langchain_core.documents import Document

from app.core.config import settings


def _get_recursive_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", "。", ".", " ", ""],
    )


def _get_markdown_header_splitter() -> MarkdownHeaderTextSplitter:
    return MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "h1"),
            ("##", "h2"),
            ("###", "h3"),
        ],
        strip_headers=False,
    )


def _split_markdown(documents: list[Document]) -> list[Document]:
    """Split markdown documents preserving header hierarchy metadata."""
    header_splitter = _get_markdown_header_splitter()
    recursive_splitter = _get_recursive_splitter()
    result = []

    for doc in documents:
        # First, split by markdown headers
        header_splits = header_splitter.split_text(doc.page_content)

        for hs in header_splits:
            # Transfer original metadata (source, file_path, etc.) to header splits
            hs.metadata.update(doc.metadata)

        # Further split any sections that exceed chunk_size
        further_splits = recursive_splitter.split_documents(header_splits)
        result.extend(further_splits)

    return result


# 将文档内容进行分割，返回分割后的Document对象列表
def split_documents(documents: list[Document]) -> list[Document]:
    md_docs = []
    other_docs = []

    for doc in documents:
        file_type = doc.metadata.get("file_type", "")
        if file_type in (".md", ".markdown"):
            md_docs.append(doc)
        else:
            other_docs.append(doc)

    result = []

    if md_docs:
        result.extend(_split_markdown(md_docs))

    if other_docs:
        splitter = _get_recursive_splitter()
        result.extend(splitter.split_documents(other_docs))

    return result

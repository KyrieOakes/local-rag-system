"""
RAG 查询的请求/响应 Pydantic 模型。

定义三个数据模型：
- QueryRequest — 用户查询请求（包含 question 字段，最少 1 个字符）
- SourceChunk — 检索到的文档块信息（内容、来源、文件名、路径、页码、评分）
- QueryResponse — RAG 查询完整响应（问题、答案、文档块列表）

这些模型同时用于 FastAPI 的自动文档生成（response_model）和请求校验。
"""

from pydantic import BaseModel, Field

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="User question")

# 检索到的文本块模型，包含内容、来源、页码和相关性评分
class SourceChunk(BaseModel):
    content: str
    source: str | None = None      # 原始文件名（前端展示用）
    file_name: str | None = None   # 文件名
    file_path: str | None = None   # 文件完整路径
    chunk_index: int | None = None # chunk 在文件中的序号
    page: int | None = None        # PDF 页码（仅 PDF 文件有值）
    score: float | None = None

# RAG 的响应模型，包含原始问题、生成的答案和相关文本块列表
class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceChunk]
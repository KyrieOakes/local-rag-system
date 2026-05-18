from pydantic import BaseModel, Field

# RAG 的请求和响应模型
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
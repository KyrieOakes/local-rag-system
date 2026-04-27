from pydantic import BaseModel, Field

# RAG 的请求和响应模型
class QueryRequest(BaseModel):
    # 用户输入的自然语言问题，要求至少1个字符
    # Field函数用于定义字段的验证规则和描述信息
    question: str = Field(..., min_length=1, description="User question")
    # 需要检索的相关文本块数量，默认为5，范围为1到20
    top_k: int = Field(default=5, ge=1, le=20, description="Number of retrieved chunks")

# 检索到的文本块模型，包含内容、来源、页码和相关性评分
class SourceChunk(BaseModel):
    content: str
    source: str | None = None
    page: int | None = None
    score: float | None = None

# RAG 的响应模型，包含原始问题、生成的答案和相关文本块列表
class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceChunk]
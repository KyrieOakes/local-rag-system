"""
RAG 查询的请求/响应 Pydantic 模型。

数据模型：
- Message — 单条对话消息（role + content）
- QueryRequest — 用户查询请求（question, conversation_id, history, force_rag）
- SourceChunk — 检索到的文档块信息（内容、来源、文件名、路径、页码、评分）
- QueryResponse — RAG 查询完整响应（问题、答案、文档块列表、conversation_id、路由决策）
"""

from pydantic import BaseModel, Field


class Message(BaseModel):
    """单条对话消息，用于传递多轮对话历史。"""
    role: str = Field(..., pattern="^(user|assistant)$", description="消息角色")
    content: str = Field(..., description="消息文本内容")


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="User question")
    conversation_id: str | None = Field(None, description="Conversation ID (null = new conversation)")
    history: list[Message] = Field(default_factory=list, description="Recent conversation messages for context")
    force_rag: bool = Field(False, description="Force RAG retrieval regardless of routing decision")


class SourceChunk(BaseModel):
    content: str
    source: str | None = None
    file_name: str | None = None
    file_path: str | None = None
    chunk_index: int | None = None
    page: int | None = None
    score: float | None = None


class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceChunk]
    conversation_id: str
    routing: str  # "rag" | "direct" | "greeting"
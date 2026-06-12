"""
Pydantic models for conversation persistence.

ConversationSummary — lightweight sidebar listing (no messages).
ConversationDetail — full conversation with all messages.
MessageDetail  — single message within a conversation.
"""

from __future__ import annotations

from pydantic import BaseModel


class MessageDetail(BaseModel):
    role: str  # "user" | "assistant"
    content: str
    sources: list | None = None
    routing: str | None = None
    created_at: float | None = None


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: float | None = None
    updated_at: float | None = None
    message_count: int = 0


class ConversationDetail(BaseModel):
    id: str
    title: str
    created_at: float | None = None
    updated_at: float | None = None
    messages: list[MessageDetail] = []

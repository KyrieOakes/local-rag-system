"""
Conversations REST API.

Endpoints:
  GET  /conversations           — list all conversations (sidebar)
  GET  /conversations/{id}      — get conversation with messages
  DELETE /conversations/{id}    — delete conversation and its messages
"""

import logging

from fastapi import APIRouter, HTTPException

from app.rag.conversation_store import get_conversation_store
from app.schemas.conversation import ConversationDetail, ConversationSummary

router = APIRouter(prefix="/conversations", tags=["Conversations"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[ConversationSummary])
def list_conversations():
    """List all conversations, newest first. Returns [] when empty."""
    try:
        store = get_conversation_store()
        return store.list_conversations()
    except Exception:
        logger.exception("Failed to list conversations")
        raise HTTPException(status_code=500, detail="Failed to list conversations.")


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str):
    """Get a conversation with all its messages."""
    try:
        store = get_conversation_store()
        result = store.get_conversation(conversation_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return ConversationDetail(**result)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get conversation %s", conversation_id)
        raise HTTPException(status_code=500, detail="Failed to get conversation.")


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str):
    """Delete a conversation and all its messages."""
    try:
        store = get_conversation_store()
        deleted = store.delete_conversation(conversation_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"ok": True, "deleted": conversation_id}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete conversation %s", conversation_id)
        raise HTTPException(status_code=500, detail="Failed to delete conversation.")

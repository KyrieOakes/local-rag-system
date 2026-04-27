from fastapi import APIRouter, HTTPException

from app.schemas.rag import QueryRequest, QueryResponse
from app.services.rag_service import query_rag


router = APIRouter(prefix="/rag", tags=["RAG"])


@router.post("/query", response_model=QueryResponse)
def rag_query(request: QueryRequest):
    try:
        return query_rag(
            question=request.question,
            top_k=request.top_k,
        )

    except Exception as error:
        raise HTTPException(status_code=500, detail=f"RAG query failed: {error}")

"""Shared Qdrant BM25 document/query construction.

Ingestion and retrieval must use identical text processing options. Keeping
the construction behind one helper prevents an index/query tokenizer drift.
"""

from qdrant_client import models

from app.core.config import settings


def build_bm25_document(text: str) -> models.Document:
    """Build a server-side BM25 input with the configured text processing."""
    return models.Document(
        text=text,
        model=settings.bm25_model,
        options=models.Bm25Config(
            tokenizer=models.TokenizerType(settings.bm25_tokenizer),
            language=settings.bm25_language,
        ),
    )

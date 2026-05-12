import logging
import time

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_client() -> OpenAI:
    return OpenAI(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
    )


def embed_texts(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    """Batch-embed a list of texts using the OpenAI-compatible embeddings API.

    Sends ``batch_size`` texts per API call. Returns embeddings in the same
    order as the input texts.
    """
    if not texts:
        return []

    client = _get_client()
    total = len(texts)
    total_batches = (total + batch_size - 1) // batch_size
    all_embeddings: list[list[float]] = []

    logger.info("Starting batch embedding: %d texts, batch_size=%d, %d batches",
                total, batch_size, total_batches)

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, total)
        batch = texts[start:end]

        logger.info("Embedding batch %d/%d (%d texts)", batch_idx + 1, total_batches, len(batch))

        t0 = time.perf_counter()
        try:
            response = client.embeddings.create(
                model=settings.embedding_model,
                input=batch,
            )
        except Exception:
            logger.error("Embedding batch %d/%d failed", batch_idx + 1, total_batches)
            raise

        elapsed = time.perf_counter() - t0
        sorted_items = sorted(response.data, key=lambda x: x.index)
        batch_embeddings = [item.embedding for item in sorted_items]
        all_embeddings.extend(batch_embeddings)

        logger.info("Batch %d/%d complete in %.2fs", batch_idx + 1, total_batches, elapsed)

    logger.info("All embeddings complete: %d vectors generated", len(all_embeddings))
    return all_embeddings

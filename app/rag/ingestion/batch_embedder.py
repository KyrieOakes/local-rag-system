"""
并发批量嵌入模块。

embed_texts() 将文本列表批量转换为向量嵌入：
- 使用 OpenAI 兼容的 /v1/embeddings API（直连 OpenAI 客户端，不走 LangChain）
- 按 batch_size 分批发送请求
- 使用进程内共享的有界线程池并发调用 embedding endpoint
- 返回与输入文本顺序一致的嵌入向量列表
- 每批记录耗时日志

配置（base_url、model、api_key）从 settings 读取。
"""

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed, wait
from functools import lru_cache

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_client() -> OpenAI:
    return OpenAI(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
    )


@lru_cache(maxsize=16)
def _get_embedding_executor(max_workers: int) -> ThreadPoolExecutor:
    """Return one process-wide bounded executor for a concurrency setting."""
    return ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="embedding-request",
    )


def _embed_batch(
    client: OpenAI,
    batch_index: int,
    total_batches: int,
    batch: list[str],
) -> tuple[int, list[list[float]], float]:
    logger.info(
        "Embedding batch %d/%d started (%d texts)",
        batch_index + 1,
        total_batches,
        len(batch),
    )
    started = time.perf_counter()
    try:
        response = client.embeddings.create(
            model=settings.embedding_model,
            input=batch,
        )
    except Exception:
        logger.exception(
            "Embedding batch %d/%d failed",
            batch_index + 1,
            total_batches,
        )
        raise

    sorted_items = sorted(response.data, key=lambda item: item.index)
    actual_indexes = [item.index for item in sorted_items]
    expected_indexes = list(range(len(batch)))
    if actual_indexes != expected_indexes:
        raise ValueError(
            "Embedding endpoint returned incomplete or invalid batch indexes: "
            f"expected {expected_indexes}, got {actual_indexes}"
        )

    elapsed = time.perf_counter() - started
    embeddings = [item.embedding for item in sorted_items]
    logger.info(
        "Embedding batch %d/%d complete in %.2fs",
        batch_index + 1,
        total_batches,
        elapsed,
    )
    return batch_index, embeddings, elapsed


def embed_texts(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    """Batch-embed a list of texts using the OpenAI-compatible embeddings API.

    Sends ``batch_size`` texts per API call. Returns embeddings in the same
    order as the input texts.
    """
    if not texts:
        return []

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    client = _get_client()
    total = len(texts)
    total_batches = (total + batch_size - 1) // batch_size
    max_concurrency = min(
        settings.embedding_max_concurrency,
        total_batches,
    )
    embeddings_by_batch: list[list[list[float]] | None] = [
        None
    ] * total_batches

    logger.info(
        "Starting batch embedding: %d texts, batch_size=%d, batches=%d, "
        "max_concurrency=%d",
        total,
        batch_size,
        total_batches,
        max_concurrency,
    )

    executor = _get_embedding_executor(settings.embedding_max_concurrency)
    futures: list[Future] = []
    try:
        for batch_index in range(total_batches):
            start = batch_index * batch_size
            end = min(start + batch_size, total)
            futures.append(
                executor.submit(
                    _embed_batch,
                    client,
                    batch_index,
                    total_batches,
                    texts[start:end],
                )
            )

        for future in as_completed(futures):
            batch_index, batch_embeddings, _elapsed = future.result()
            embeddings_by_batch[batch_index] = batch_embeddings
    except Exception:
        for future in futures:
            future.cancel()
        # Running HTTP calls cannot be force-cancelled safely. Wait for those
        # bounded workers before closing the shared client for this invocation.
        wait(futures)
        raise
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    if any(batch is None for batch in embeddings_by_batch):
        raise RuntimeError("Embedding execution finished with a missing batch")
    all_embeddings = [
        vector
        for batch in embeddings_by_batch
        if batch is not None
        for vector in batch
    ]
    logger.info(
        "All embeddings complete: %d vectors generated across %d batches",
        len(all_embeddings),
        total_batches,
    )
    return all_embeddings

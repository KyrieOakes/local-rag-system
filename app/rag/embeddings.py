"""
嵌入模型模块。

提供 CachedOpenAIEmbeddings 类（继承自 LangChain 的 OpenAIEmbeddings），
在 embed_query() 调用时自动记录耗时日志，并通过 LRU 缓存避免重复嵌入计算。

get_embedding_model() 工厂函数返回配置好的嵌入模型实例，
连接地址和模型名从 settings 读取（默认指向本地 LM Studio 的 text-embedding-qwen3-embedding-4b）。
"""

import hashlib
import logging
import threading
import time

from langchain_openai import OpenAIEmbeddings

from app.core.config import settings

logger = logging.getLogger(__name__)

_CACHE_MAX_SIZE = 256
_embedding_cache: dict[str, list[float]] = {}
_cache_lock = threading.Lock()
_cache_hits = 0
_cache_misses = 0


class CachedOpenAIEmbeddings(OpenAIEmbeddings):
    """OpenAIEmbeddings subclass with LRU-style cache for repeated queries."""

    def embed_query(self, text: str) -> list[float]:
        global _cache_hits, _cache_misses
        cache_key = hashlib.md5(text.encode("utf-8")).hexdigest()

        with _cache_lock:
            if cache_key in _embedding_cache:
                _cache_hits += 1
                logger.debug("Embedding cache hit (#%d hits, #%d misses)", _cache_hits, _cache_misses)
                return _embedding_cache[cache_key]

        step2_start = time.perf_counter()
        logger.info("[RAG][STEP 2] embedding 开始")
        embedded = super().embed_query(text)
        logger.info("[RAG][STEP 2] embedding 完成，耗时 %.3fs", time.perf_counter() - step2_start)

        with _cache_lock:
            if len(_embedding_cache) >= _CACHE_MAX_SIZE:
                # Evict oldest entry (first key)
                oldest = next(iter(_embedding_cache))
                del _embedding_cache[oldest]
            _embedding_cache[cache_key] = embedded
            _cache_misses += 1

        return embedded


def get_embedding_model() -> OpenAIEmbeddings:
    return CachedOpenAIEmbeddings(
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        check_embedding_ctx_length=False,
    )
"""
Reranker 模块 — 在向量检索后对候选文档进行精排序。

架构：可插拔的抽象设计，通过配置切换不同策略。
  - NoOpReranker: 透传，不做 rerank（等同于禁用）
  - CrossEncoderReranker: 本地 sentence-transformers Cross-Encoder 精排
  - HybridFusionReranker: 向量分数 + 关键词分数加权融合（轻量 fallback，无额外模型）

工作流：
  1. Vector Search 召回 top_n 候选（如 20 条）
  2. Reranker 对候选精排
  3. 取最终 top_k（如 5 条）送入 LLM

每个 reranker 实例是全局单例，模型在首次调用时懒加载，后续请求复用。
"""

from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod

from langchain_core.documents import Document

from app.core.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------

class BaseReranker(ABC):
    """所有 reranker 的抽象基类。"""

    @abstractmethod
    def rerank(
        self, query: str, documents: list[Document], top_k: int
    ) -> list[tuple[Document, float]]:
        """
        对候选文档精排，返回 (Document, score) 列表，按分数降序。

        参数:
            query: 用户查询文本
            documents: Vector Search 召回的候选文档列表
            top_k: 最终保留条数

        返回:
            list[tuple[Document, float]]: 排序后的 (文档, 分数) 列表，长度 ≤ top_k
        """
        ...


# ---------------------------------------------------------------------------
# NoOp — 禁用 rerank 时的透传实现
# ---------------------------------------------------------------------------

class NoOpReranker(BaseReranker):
    """透传 reranker：不做任何重排，直接返回前 top_k 条。"""

    def rerank(
        self, query: str, documents: list[Document], top_k: int
    ) -> list[tuple[Document, float]]:
        results: list[tuple[Document, float]] = [
            (doc, doc.metadata.get("score", 0.0)) for doc in documents
        ]
        return results[:top_k]


# ---------------------------------------------------------------------------
# Cross-Encoder Reranker — 本地 sentence-transformers 模型
# ---------------------------------------------------------------------------

class CrossEncoderReranker(BaseReranker):
    """
    使用 sentence-transformers CrossEncoder 进行 pairwise 相关性打分。

    模型: BAAI/bge-reranker-base（默认）或 BAAI/bge-reranker-v2-m3
    输入: (query, document_text) 对
    输出: 相关性分数（越高越相关）

    特性:
      - 懒加载：首次调用 rerank() 时才加载模型，避免服务启动阻塞
      - Fallback: 模型加载失败时退回 vector-only 结果
      - 文档截断: 每个 doc 最多取前 max_chars 字符送入模型
      - 元数据保持: 在 doc.metadata 中记录 vector_score 和 rerank_score
    """

    def __init__(
        self,
        model_name: str | None = None,
        max_chars: int | None = None,
        device: str | None = None,
    ):
        self._model_name = model_name or settings.reranker_model
        self._max_chars = max_chars or settings.reranker_max_chars
        self._device = device or settings.reranker_device
        self._model = None  # 懒加载

    def _load_model(self):
        """懒加载 CrossEncoder 模型（仅首次调用时执行）。"""
        if self._model is not None:
            return

        logger.info(
            "[RERANK] 加载 CrossEncoder 模型: %s (device=%s)",
            self._model_name, self._device,
        )
        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(
                self._model_name,
                device=self._device,
                trust_remote_code=True,
            )
            logger.info("[RERANK] 模型加载完成")
        except Exception as exc:
            logger.error("[RERANK] 模型加载失败: %s", exc)
            raise

    def rerank(
        self, query: str, documents: list[Document], top_k: int
    ) -> list[tuple[Document, float]]:
        """
        对候选文档进行 Cross-Encoder 精排。

        流程:
          1. 懒加载模型（首次调用）
          2. 对每个 doc 截断文本（默认 1500 字符），构造 (query, doc_text) 对
          3. 模型批量预测相关性分数
          4. 按分数降序排序，保留 top_k
          5. 在 metadata 中记录 vector_score 和 rerank_score
        """
        if not documents:
            return []

        # 候选数 ≤ top_k 时无需 rerank
        if len(documents) <= top_k:
            logger.info(
                "[RERANK] 候选数 %d ≤ top_k=%d，跳过 rerank",
                len(documents), top_k,
            )
            return [
                (doc, doc.metadata.get("score", 0.0)) for doc in documents
            ]

        try:
            self._load_model()
        except Exception:
            logger.warning(
                "[RERANK] 模型加载失败，退回 vector-only 结果"
            )
            return _fallback_vector_only(documents, top_k)

        step_start = time.perf_counter()

        # 构造 (query, doc_text) pairs，限制每个 doc 最大字符数
        pairs: list[tuple[str, str]] = [
            (query, doc.page_content[: self._max_chars]) for doc in documents
        ]

        try:
            scores: list[float] = self._model.predict(
                pairs,
                show_progress_bar=False,
            ).tolist()
        except Exception as exc:
            logger.warning(
                "[RERANK] Cross-Encoder 预测失败，退回 vector-only 结果: %s", exc
            )
            return _fallback_vector_only(documents, top_k)

        # 组装 (doc, vector_score, rerank_score)
        scored: list[dict] = []
        for doc, score in zip(documents, scores):
            scored.append({
                "doc": doc,
                "vector_score": doc.metadata.get("score", 0.0),
                "rerank_score": float(score),
            })

        # 按 rerank_score 降序排序
        scored.sort(key=lambda x: x["rerank_score"], reverse=True)

        # 保留 top_k，同时写回 metadata
        reranked: list[tuple[Document, float]] = []
        for item in scored[:top_k]:
            doc = item["doc"]
            doc.metadata["vector_score"] = item["vector_score"]
            doc.metadata["rerank_score"] = item["rerank_score"]
            doc.metadata["score"] = item["rerank_score"]  # 更新为 rerank 分数
            reranked.append((doc, item["rerank_score"]))

        elapsed = time.perf_counter() - step_start
        logger.info(
            "[RERANK] Cross-Encoder 完成，%d → %d 条，耗时 %.3fs",
            len(documents), len(reranked), elapsed,
        )

        return reranked


# ---------------------------------------------------------------------------
# Hybrid Fusion Reranker — 向量 + 关键词加权融合（轻量，无额外模型）
# ---------------------------------------------------------------------------

class HybridFusionReranker(BaseReranker):
    """
    混合融合 reranker：将向量相似度分数与关键词匹配分数加权求和。

    无需额外模型，适合作为轻量 fallback 或不便加载 Cross-Encoder 的场景。

    公式: final_score = alpha * normalized_vector_score + (1-alpha) * keyword_score
    """

    def __init__(self, alpha: float = 0.7):
        self._alpha = alpha

    def rerank(
        self, query: str, documents: list[Document], top_k: int
    ) -> list[tuple[Document, float]]:
        if not documents:
            return []

        if len(documents) <= top_k:
            return [
                (doc, doc.metadata.get("score", 0.0)) for doc in documents
            ]

        step_start = time.perf_counter()

        # 提取原始向量分数
        vector_scores = [
            doc.metadata.get("score", 0.0) for doc in documents
        ]

        # Min-max 归一化到 [0, 1]
        v_min, v_max = min(vector_scores), max(vector_scores)
        if v_max - v_min > 1e-8:
            norm_vector = [
                (s - v_min) / (v_max - v_min) for s in vector_scores
            ]
        else:
            norm_vector = [0.5] * len(vector_scores)

        # 关键词匹配分数（简单 BM25-like token overlap）
        query_tokens = set(_tokenize(query))
        keyword_scores = _compute_keyword_scores(query_tokens, documents)

        # 加权融合
        scored: list[dict] = []
        for doc, nv, kw in zip(documents, norm_vector, keyword_scores):
            fused = self._alpha * nv + (1 - self._alpha) * kw
            scored.append({
                "doc": doc,
                "vector_score": doc.metadata.get("score", 0.0),
                "keyword_score": kw,
                "rerank_score": fused,
            })

        scored.sort(key=lambda x: x["rerank_score"], reverse=True)

        reranked: list[tuple[Document, float]] = []
        for item in scored[:top_k]:
            doc = item["doc"]
            doc.metadata["vector_score"] = item["vector_score"]
            doc.metadata["keyword_score"] = item["keyword_score"]
            doc.metadata["rerank_score"] = item["rerank_score"]
            doc.metadata["score"] = item["rerank_score"]
            reranked.append((doc, item["rerank_score"]))

        elapsed = time.perf_counter() - step_start
        logger.info(
            "[RERANK] HybridFusion 完成，%d → %d 条，耗时 %.3fs",
            len(documents), len(reranked), elapsed,
        )

        return reranked


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

_reranker: BaseReranker | None = None


def get_reranker() -> BaseReranker:
    """返回全局 reranker 单例，根据 settings.reranker_type 选择实现。"""
    global _reranker
    if _reranker is not None:
        return _reranker

    reranker_type = settings.reranker_type.lower()
    logger.info("[RERANK] 初始化 reranker，类型: %s", reranker_type)

    if reranker_type == "cross_encoder":
        _reranker = CrossEncoderReranker()
    elif reranker_type == "hybrid":
        _reranker = HybridFusionReranker()
    else:
        _reranker = NoOpReranker()

    return _reranker


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """简单分词：小写 + 字母数字 token（用于关键词匹配）。"""
    return re.findall(r"[a-zA-Z0-9一-鿿]+", text.casefold())


def _compute_keyword_scores(
    query_tokens: set[str], documents: list[Document]
) -> list[float]:
    """计算每个文档对查询 token 的覆盖比例。"""
    if not query_tokens:
        return [0.0] * len(documents)

    scores: list[float] = []
    for doc in documents:
        doc_tokens = set(_tokenize(doc.page_content))
        if not doc_tokens:
            scores.append(0.0)
        else:
            overlap = len(query_tokens & doc_tokens)
            scores.append(overlap / len(query_tokens))
    return scores


def _fallback_vector_only(
    documents: list[Document], top_k: int
) -> list[tuple[Document, float]]:
    """退回 vector-only：按原始分数排序，保留 top_k。"""
    results = [
        (doc, doc.metadata.get("score", 0.0)) for doc in documents
    ]
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]

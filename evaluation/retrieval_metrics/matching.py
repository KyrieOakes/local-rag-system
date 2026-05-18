"""
检索结果与标注数据匹配模块。

核心挑战：Golden 数据集中的标注是文档级别的（file_path/source/text 片段），
但检索器返回的是经过切分后的具体 chunk。本模块负责将两者关联起来。

数据类：
- RetrievedItem — 检索器返回的单个结果（id, content, metadata, score）
- RelevantSource — Golden 数据集中标注的相关文档（file_path, source, text, relevance）
- MatchedRelevance — 匹配结果（retrieved_ids, relevant_ids, relevance_scores）

核心函数：
- build_retrieved_item() — 从检索结果构造 RetrievedItem
- relevant_source_from_dict() — 从 JSONL 字典构造 RelevantSource
- match_retrieved_to_relevant_sources() — 将标注的相关文档映射到具体的检索 chunk ID
  支持按 file_path、source、file_name、text 片段进行匹配（大小写和空白容忍）
  未匹配到的标注会保留在 relevance_scores 中（用于 NDCG 的理想排序计算）
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetrievedItem:
    id: str
    content: str
    metadata: Mapping[str, Any]
    score: float | None = None


@dataclass(frozen=True)
class RelevantSource:
    file_path: str | None = None
    source: str | None = None
    file_name: str | None = None
    text: str | None = None
    relevance: float = 1.0


@dataclass(frozen=True)
class MatchedRelevance:
    retrieved_ids: list[str]
    relevant_ids: set[str]
    relevance_scores: dict[str, float]


def make_retrieved_item_id(content: str, metadata: Mapping[str, Any]) -> str:
    """Create a stable-enough ID for evaluation from chunk metadata and content."""
    file_path = metadata.get("file_path") or metadata.get("source") or "unknown"
    chunk_index = metadata.get("chunk_index")
    if chunk_index is not None and chunk_index != -1:
        return f"{file_path}#chunk:{chunk_index}"

    content_hash = hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
    return f"{file_path}#content:{content_hash}"


def build_retrieved_item(content: str, metadata: Mapping[str, Any], score: float | None = None) -> RetrievedItem:
    return RetrievedItem(
        id=make_retrieved_item_id(content, metadata),
        content=content,
        metadata=metadata,
        score=score,
    )


def relevant_source_from_dict(data: Mapping[str, Any]) -> RelevantSource:
    return RelevantSource(
        file_path=data.get("file_path"),
        source=data.get("source"),
        file_name=data.get("file_name"),
        text=data.get("text"),
        relevance=float(data.get("relevance", 1.0)),
    )


def match_retrieved_to_relevant_sources(
    retrieved_items: Sequence[RetrievedItem],
    relevant_sources: Sequence[RelevantSource],
) -> MatchedRelevance:
    """Map source/snippet labels onto concrete retrieved item IDs.

    This keeps evaluation useful when chunking strategy changes. Labels can point
    to stable document-level fields (`file_path`, `source`, `file_name`) and may
    optionally require a text snippet to appear inside the retrieved chunk.
    """
    retrieved_ids = [item.id for item in retrieved_items]
    relevant_ids: set[str] = set()
    relevance_scores: dict[str, float] = {}

    for label_index, relevant_source in enumerate(relevant_sources):
        matched_ids = [
            item.id
            for item in retrieved_items
            if _matches_relevant_source(item, relevant_source)
        ]

        if matched_ids:
            for item_id in matched_ids:
                relevant_ids.add(item_id)
                relevance_scores[item_id] = max(
                    relevance_scores.get(item_id, 0.0),
                    relevant_source.relevance,
                )
        else:
            # Keep unmatched expected evidence in the ideal ranking for NDCG.
            relevance_scores[f"expected:{label_index}"] = relevant_source.relevance

    return MatchedRelevance(
        retrieved_ids=retrieved_ids,
        relevant_ids=relevant_ids,
        relevance_scores=relevance_scores,
    )


def _matches_relevant_source(item: RetrievedItem, relevant_source: RelevantSource) -> bool:
    metadata = item.metadata

    if relevant_source.file_path and metadata.get("file_path") != relevant_source.file_path:
        return False

    if relevant_source.source and metadata.get("source") != relevant_source.source:
        return False

    if relevant_source.file_name and metadata.get("file_name") != relevant_source.file_name:
        return False

    if relevant_source.text and _normalize(relevant_source.text) not in _normalize(item.content):
        return False

    return any([
        relevant_source.file_path,
        relevant_source.source,
        relevant_source.file_name,
        relevant_source.text,
    ])


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


"""
检索结果与标注数据匹配模块。

核心挑战：Golden 数据集中的标注是稳定 evidence/label，
但检索器返回的是经过切分后的具体 chunk。本模块负责将两者关联起来。

数据类：
- RetrievedItem — 检索器返回的单个结果（id, content, metadata, score）
- RelevantSource — Golden 数据集中标注的相关文档（file_path, source, text, relevance）
- MatchedRelevance — 每个检索 rank 匹配到的 evidence ID、完整 gold evidence 集合

核心函数：
- build_retrieved_item() — 从检索结果构造 RetrievedItem
- relevant_source_from_dict() — 从 JSONL 字典构造 RelevantSource
- match_retrieved_to_relevant_sources() — 将检索 chunk 映射到稳定 evidence ID
  支持按 file_path、source、file_name、text 片段进行匹配（大小写和空白容忍）
  未匹配到的 evidence 仍保留在分母中，避免 Recall 被命中结果反向定义
"""

from __future__ import annotations

import hashlib
import json
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
    evidence_id: str | None = None


@dataclass(frozen=True)
class MatchedRelevance:
    retrieved_ids: list[str]
    evidence_ids: list[str]
    evidence_scores: dict[str, float]
    evidence_matches_by_rank: list[tuple[str, ...]]
    matched_chunk_ids: set[str]

    @property
    def matched_evidence_ids(self) -> set[str]:
        return {
            evidence_id
            for matches in self.evidence_matches_by_rank
            for evidence_id in matches
        }

    @property
    def ranked_evidence_ids(self) -> list[str]:
        """Return evidence in first-hit order, counting each label once."""
        ranked = []
        seen = set()
        for matches in self.evidence_matches_by_rank:
            for evidence_id in matches:
                if evidence_id not in seen:
                    seen.add(evidence_id)
                    ranked.append(evidence_id)
        return ranked


def make_retrieved_item_id(content: str, metadata: Mapping[str, Any]) -> str:
    """Create a stable-enough ID for evaluation from chunk metadata and content."""
    file_path = metadata.get("file_path") or metadata.get("source") or "unknown"
    chunk_index = metadata.get("chunk_index")
    if chunk_index is not None and chunk_index != -1:
        return f"{file_path}#chunk:{chunk_index}"

    content_hash = hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
    return f"{file_path}#content:{content_hash}"


def make_evidence_id(relevant_source: RelevantSource) -> str:
    """Return a stable ID for a gold evidence label.

    Datasets may provide an explicit ``evidence_id``. Older datasets remain
    compatible because a deterministic hash is derived from the label fields.
    """
    if relevant_source.evidence_id:
        return str(relevant_source.evidence_id)

    canonical = {
        "file_path": relevant_source.file_path or "",
        "source": relevant_source.source or "",
        "file_name": relevant_source.file_name or "",
        "text": _normalize(relevant_source.text or ""),
    }
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"evidence:{digest}"


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
        evidence_id=data.get("evidence_id") or data.get("label_id"),
    )


def match_retrieved_to_relevant_sources(
    retrieved_items: Sequence[RetrievedItem],
    relevant_sources: Sequence[RelevantSource],
) -> MatchedRelevance:
    """Map retrieved chunks onto stable source/snippet evidence labels.

    This keeps evaluation useful when chunking strategy changes. Labels can point
    to stable document-level fields (`file_path`, `source`, `file_name`) and may
    optionally require a text snippet to appear inside the retrieved chunk.
    """
    retrieved_ids = [item.id for item in retrieved_items]
    labels: list[tuple[str, RelevantSource]] = []
    evidence_ids: list[str] = []
    evidence_scores: dict[str, float] = {}
    for relevant_source in relevant_sources:
        evidence_id = make_evidence_id(relevant_source)
        labels.append((evidence_id, relevant_source))
        if evidence_id not in evidence_scores:
            evidence_ids.append(evidence_id)
        evidence_scores[evidence_id] = max(
            evidence_scores.get(evidence_id, 0.0),
            relevant_source.relevance,
        )

    evidence_matches_by_rank: list[tuple[str, ...]] = []
    matched_chunk_ids: set[str] = set()
    for item in retrieved_items:
        matches = []
        seen_for_chunk = set()
        for evidence_id, relevant_source in labels:
            if (
                evidence_id not in seen_for_chunk
                and _matches_relevant_source(item, relevant_source)
            ):
                matches.append(evidence_id)
                seen_for_chunk.add(evidence_id)

        if matches:
            matched_chunk_ids.add(item.id)
        evidence_matches_by_rank.append(tuple(matches))

    return MatchedRelevance(
        retrieved_ids=retrieved_ids,
        evidence_ids=evidence_ids,
        evidence_scores=evidence_scores,
        evidence_matches_by_rank=evidence_matches_by_rank,
        matched_chunk_ids=matched_chunk_ids,
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

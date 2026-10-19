"""检索编排 + evidence_confidence 闸。

流程：embed → hybrid_search → rerank（精排）→ 排序 → 闸。
闸是纯函数机制：低相关（Top1 分低 / 证据少 / Top1-Top2 分差小）→ passed=False，
绝不因 spec 沉默而放行。权重/除数/阈值为待校准默认（Ruling 3），阈值暴露为 settings。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.rag.embedder import Embedder
from app.rag.reranker import Reranker


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass
class ScoredChunk:
    chunk_id: object
    score: float
    category: str
    section_path: str
    content_type: str
    snippet: str


@dataclass
class RetrievalResult:
    chunks: list[ScoredChunk]
    evidence_confidence: float
    passed: bool


def compute_evidence_confidence(top1_score: float, evidence_count: int, margin: float) -> float:
    """证据置信度 0..1：Top1 强度 + 证据条数 + Top1-Top2 分差 的加权组合。"""
    score_term = 0.5 * _clamp(top1_score / 0.6)
    count_term = 0.3 * min(evidence_count / 3, 1)
    margin_term = 0.2 * _clamp(margin / 0.15)
    return _clamp(score_term + count_term + margin_term)


def passes_gate(confidence: float) -> bool:
    return confidence >= settings.evidence_confidence_threshold


class Retriever:
    def __init__(self, embedder: Embedder, store, reranker: Reranker) -> None:
        self.embedder = embedder
        self.store = store
        self.reranker = reranker

    def retrieve(self, query: str, top_k: int = 10) -> RetrievalResult:
        dense = self.embedder.encode_dense([query])[0]
        hits = self.store.hybrid_search(dense, query, top_k)
        scores = self.reranker.rerank(query, [h["text"] for h in hits])

        chunks = [
            ScoredChunk(
                chunk_id=h["chunk_id"],
                score=scores[i],
                category=h.get("category") or "",
                section_path=h.get("section_path") or "",
                content_type=h.get("content_type") or "",
                snippet=(h["text"] or "")[:80],
            )
            for i, h in enumerate(hits)
        ]
        chunks.sort(key=lambda c: c.score, reverse=True)

        evidence_count = sum(1 for s in scores if s >= settings.rerank_min)
        top1 = chunks[0].score if chunks else 0.0
        # margin = top1 - top2；证据不足 2 条时取 0（避免单条时误计 top1-0 为正分差）。
        margin = top1 - chunks[1].score if len(chunks) > 1 else 0.0

        evidence_confidence = compute_evidence_confidence(top1, evidence_count, margin)
        return RetrievalResult(
            chunks=chunks,
            evidence_confidence=evidence_confidence,
            passed=passes_gate(evidence_confidence),
        )

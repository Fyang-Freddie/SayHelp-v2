from typing import Protocol


class Reranker(Protocol):
    def rerank(self, query: str, passages: list[str]) -> list[float]: ...


class FakeReranker:
    def rerank(self, query: str, passages: list[str]) -> list[float]:
        q = set(query)
        scores = []
        for p in passages:
            if not p:
                scores.append(0.0)
                continue
            overlap = sum(1 for ch in set(p) if ch in q)
            scores.append(min(1.0, overlap / max(len(q), 1)))
        return scores

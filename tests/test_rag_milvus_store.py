"""Task 5 — Milvus 向量库集成测试（milvus-lite 临时文件）。

真实跑 milvus-lite：create collection（BM25 Function + sparse）→ upsert 3 条
1024 维向量 → hybrid_search（dense + sparse，RRF 融合）断言 Top-1 命中正确 chunk
且分数降序。临时 db 目录由 pytest tmp_path 自动清理。
"""
import random

from app.rag.milvus_store import MilvusStore

DIM = 1024


def _vec(seed: int) -> list[float]:
    r = random.Random(seed)
    v = [r.random() for _ in range(DIM)]
    norm = sum(x * x for x in v) ** 0.5
    return [x / norm for x in v]


def _records() -> list[dict]:
    return [
        {"id": 1, "dense": _vec(1), "text": "售后服务包括补发、维修、换货。",
         "category": "售后政策", "section_path": "售后政策/A01", "content_type": "manual"},
        {"id": 2, "dense": _vec(2), "text": "以签收时间为依据起算。",
         "category": "售后政策", "section_path": "售后政策/A02", "content_type": "manual"},
        # section_path / content_type 为 None 时不能崩（存入空串）
        {"id": 3, "dense": _vec(3), "text": "退换货需要保持商品完好。",
         "category": "退换货", "section_path": None, "content_type": None},
    ]


def test_milvus_store_upsert_and_hybrid_search(tmp_path):
    db = tmp_path / "milvus.db"
    store = MilvusStore(str(db))
    try:
        store.ensure_collection()
        store.upsert(_records())

        results = store.hybrid_search(_vec(1), "售后服务补发维修", top_k=3)

        assert results, "hybrid_search 应返回结果"
        assert results[0]["chunk_id"] == 1, "Top-1 应命中补发/维修那条 chunk"

        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True), "分数应降序"

        assert set(results[0].keys()) == {
            "chunk_id", "text", "category", "section_path", "content_type", "score",
        }
        assert results[0]["category"] == "售后政策"
        assert results[0]["section_path"] == "售后政策/A01"
    finally:
        store.close()

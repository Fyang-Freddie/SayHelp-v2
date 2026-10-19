from app.rag.embedder import FakeEmbedder
from app.rag.reranker import FakeReranker
from app.rag.retrieval import Retriever


class _Store:
    def hybrid_search(self, dense, query_text, top_k):
        return [
            {"chunk_id": 3, "text": "手机保修多久 手机保修 12 个月", "category": "售后政策", "section_path": "售后政策 > A06", "content_type": "manual", "score": 0.9},
            {"chunk_id": 2, "text": "七天无理由退换货规则", "category": "售后政策", "section_path": "售后政策 > A03", "content_type": "manual", "score": 0.5},
            {"chunk_id": 1, "text": "运费承担 退货", "category": "退款退货政策", "section_path": "退款退货政策 > R31", "content_type": "policy", "score": 0.1},
        ]


def test_retrieve_reranks_and_gates():
    r = Retriever(FakeEmbedder(dim=8), _Store(), FakeReranker())
    res = r.retrieve("手机保修多久", top_k=3)
    assert res.chunks[0].chunk_id == 3  # 精排后最相关在前
    assert res.chunks[0].snippet  # 非空摘要
    assert res.evidence_confidence >= 0.0
    assert isinstance(res.passed, bool)

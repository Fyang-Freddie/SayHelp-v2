from app.rag.embedder import FakeEmbedder
from app.rag.reranker import FakeReranker


def test_fake_embedder_deterministic_and_shaped():
    e = FakeEmbedder(dim=8)
    v1 = e.encode_dense(["手机保修多久"])
    assert len(v1) == 1 and len(v1[0]) == 8
    assert v1 == e.encode_dense(["手机保修多久"])  # 确定性
    assert v1[0] != e.encode_dense(["退款规则"])[0]


def test_fake_reranker_scores_by_overlap():
    r = FakeReranker()
    q = "手机保修多久"
    scores = r.rerank(q, ["手机保修 12 个月", "退货退款运费谁出", "手机保修多久"])
    assert scores[2] > scores[0] > scores[1]

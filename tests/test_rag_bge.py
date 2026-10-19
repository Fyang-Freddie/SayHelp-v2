from app.rag.bge import BGEM3Embedder, BGEReranker


def test_bge3_embedder_declares_dim_1024():
    e = BGEM3Embedder()
    assert e.dim == 1024


def test_reranker_is_lazy():
    r = BGEReranker()
    assert r.model is None  # 未触发下载

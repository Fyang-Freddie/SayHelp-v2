# tests/test_rag_e2e.py
from app.rag.citations import build_citations
from app.rag.embedder import FakeEmbedder
from app.rag.ingest import ingest_markdown
from app.rag.reranker import FakeReranker
from app.rag.retrieval import Retriever


MD = "# 售后政策\n\n## A06【保修期限】\n手机、电脑 12 个月。\n\n## R01【退款】\n七天无理由。\n"


class _Store:
    def __init__(self):
        self.rows = []

    def upsert(self, records):
        self.rows.extend(records)

    def hybrid_search(self, dense, query_text, top_k):
        return [{"chunk_id": r["id"], "text": r["text"], "category": r["category"],
                 "section_path": r["section_path"], "content_type": r["content_type"],
                 "score": 0.8} for r in self.rows[:top_k]]


def test_e2e_ingest_retrieve_cite(db_session):
    store = _Store()
    ingest_markdown(db_session, md_text=MD, content_type="manual", root_category="售后政策",
                    embedder=FakeEmbedder(dim=8), vector_store=store)
    r = Retriever(FakeEmbedder(dim=8), store, FakeReranker())
    res = r.retrieve("手机保修多久", top_k=3)
    assert len(res.chunks) >= 1
    cites = build_citations(res.chunks)
    assert [c.index for c in cites] == list(range(1, len(cites) + 1))

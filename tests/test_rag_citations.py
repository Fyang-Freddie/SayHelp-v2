from app.rag.citations import build_citations, render_citations
from app.rag.retrieval import ScoredChunk


def _chunk(cid, path):
    return ScoredChunk(chunk_id=cid, score=0.9, category="售后政策", section_path=path,
                       content_type="manual", snippet="正文片段")


def test_citations_numbered_and_mapped():
    chunks = [_chunk(1, "售后政策 > A03【七天】"), _chunk(2, "售后政策 > A06【保修】")]
    cites = build_citations(chunks)
    assert [c.index for c in cites] == [1, 2]
    assert cites[0].chunk_id == 1 and cites[0].section_path == "售后政策 > A03【七天】"
    assert "A06" in render_citations(cites)

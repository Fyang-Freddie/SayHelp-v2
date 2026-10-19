from app.models import KnowledgeChunk
from app.rag.embedder import FakeEmbedder
from app.rag.ingest import ingest_markdown


MD = "# 售后政策\n\n## A01【售后类型】\n售后服务包括补发、维修、换货。\n\n## A02【起算】\n以签收时间为依据。\n"


class _RecordingStore:
    def __init__(self):
        self.upserted: list = []

    def upsert(self, records):
        self.upserted.extend(records)


def test_ingest_dual_write_and_idempotent(db_session):
    store = _RecordingStore()
    r1 = ingest_markdown(db_session, md_text=MD, content_type="manual",
                         root_category="售后政策", embedder=FakeEmbedder(), vector_store=store)
    assert r1["inserted"] == 2
    assert len(store.upserted) == 2

    rows = db_session.query(KnowledgeChunk).all()
    assert all(r.vectorize_status.value == "done" for r in rows)
    assert all(r.vector_id == str(r.id) for r in rows)

    # 幂等：再跑一遍不新增、不重复 upsert
    store2 = _RecordingStore()
    r2 = ingest_markdown(db_session, md_text=MD, content_type="manual",
                         root_category="售后政策", embedder=FakeEmbedder(), vector_store=store2)
    assert r2["inserted"] == 0 and r2["skipped"] == 2
    assert store2.upserted == []  # done 的 chunk 不重复 embed
    assert db_session.query(KnowledgeChunk).count() == 2


def test_ingest_dedupes_within_batch(db_session):
    dup_md = "# 售后政策\n\n## A01【售后类型】\n售后服务包括补发。\n\n## A01【售后类型】\n重复标题。\n"
    store = _RecordingStore()
    r = ingest_markdown(db_session, md_text=dup_md, content_type="manual",
                        root_category="售后政策", embedder=FakeEmbedder(), vector_store=store)
    assert r["inserted"] == 1
    assert db_session.query(KnowledgeChunk).count() == 1
    assert len(store.upserted) == 1

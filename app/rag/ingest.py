from typing import Protocol

from sqlalchemy.orm import Session

from app.models import KnowledgeChunk
from app.rag.chunk import split_policy_markdown
from app.rag.embedder import Embedder


class VectorStore(Protocol):
    def upsert(self, records: list) -> None: ...


def ingest_markdown(session: Session, *, md_text: str, content_type: str,
                    root_category: str, embedder: Embedder, vector_store: VectorStore) -> dict:
    drafts = split_policy_markdown(md_text, content_type=content_type, root_category=root_category)

    # 1) 先写 MySQL（pending），以 (category, questions) 去重避免重复行
    existing = {
        (c.category, c.questions)
        for c in session.query(KnowledgeChunk.category, KnowledgeChunk.questions).all()
    }
    seen = set(existing)
    new_drafts = []
    for d in drafts:
        key = (d.category, d.questions)
        if key not in seen:
            seen.add(key)
            new_drafts.append(d)
    new_chunks = [KnowledgeChunk(
        category=d.category, questions=d.questions, answer=d.answer,
        section_path=d.section_path, content_type=d.content_type, is_key_clause=d.is_key_clause,
    ) for d in new_drafts]
    session.add_all(new_chunks)
    session.commit()
    for c in new_chunks:
        session.refresh(c)

    # 2) 只处理 pending（重跑不重复 embed 已 done 的行）
    pending = session.query(KnowledgeChunk).filter(KnowledgeChunk.vectorize_status == "pending").all()
    if pending:
        texts = [f"{c.category} {c.questions} {c.answer}" for c in pending]
        vectors = embedder.encode_dense(texts)
        vector_store.upsert([
            {"id": c.id, "dense": v, "text": texts[i], "category": c.category,
             "section_path": c.section_path, "content_type": c.content_type}
            for i, (c, v) in enumerate(zip(pending, vectors))
        ])
        for c in pending:
            c.vector_id = str(c.id)
            c.vectorize_status = "done"
        session.commit()

    skipped = len(drafts) - len(new_drafts)
    return {"inserted": len(new_drafts), "vectorized": len(pending), "skipped": skipped}

from pathlib import Path

from app.db import SessionLocal
from app.rag.embedder import FakeEmbedder  # 真实 BGE-M3 在 Task 4 替换
from app.rag.ingest import ingest_markdown


KNOWLEDGE_DB = Path(__file__).resolve().parents[2] / "knowledge_db"
POLICY_FILES = [
    ("after-sales-manual.md", "manual", "售后政策"),
    ("returns-policy.md", "policy", "退款退货政策"),
    ("product-specifications.md", "manual", "商品规格手册"),
]


class _NoopStore:
    def upsert(self, records):
        pass


def main() -> None:
    store = _NoopStore()  # Task 5 换成真实 Milvus
    with SessionLocal() as session:
        for fname, ctype, root in POLICY_FILES:
            md = (KNOWLEDGE_DB / fname).read_text(encoding="utf-8")
            report = ingest_markdown(session, md_text=md, content_type=ctype,
                                     root_category=root, embedder=FakeEmbedder(), vector_store=store)
            print(fname, report)


if __name__ == "__main__":
    main()

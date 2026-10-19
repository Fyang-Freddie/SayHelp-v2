import argparse
from pathlib import Path

from app.db import SessionLocal
from app.rag.embedder import FakeEmbedder
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
    parser = argparse.ArgumentParser(description="SayHelp 知识库导入")
    parser.add_argument("--real", action="store_true",
                        help="真实向量化：BGEM3Embedder + MilvusStore（需 Milvus 与真实模型）")
    args = parser.parse_args()

    if args.real:
        from app.config import settings
        from app.rag.bge import BGEM3Embedder
        from app.rag.milvus_store import MilvusStore

        store = MilvusStore(settings.milvus_uri)
        store.ensure_collection()
        embedder = BGEM3Embedder()
        mark_done = True
    else:
        store = _NoopStore()
        embedder = FakeEmbedder()
        mark_done = False

    with SessionLocal() as session:
        for fname, ctype, root in POLICY_FILES:
            md = (KNOWLEDGE_DB / fname).read_text(encoding="utf-8")
            report = ingest_markdown(session, md_text=md, content_type=ctype,
                                     root_category=root, embedder=embedder,
                                     vector_store=store, mark_done=mark_done)
            print(fname, report)

    if not args.real:
        print("已写入 MySQL（pending，未向量化）；真实向量化请用 --real（需 Milvus + 真实模型）。")


if __name__ == "__main__":
    main()

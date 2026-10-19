"""端到端检索 CLI：``python -m app.rag.search "查询文本"``。

默认（fake）路径（``real=False``）：读取 3 个政策 md → ``split_policy_markdown`` 切分 →
``FakeEmbedder`` 嵌入 → 内存 store → ``Retriever`` 检索（``FakeReranker`` 精排）→
``build_citations`` 构建引用 → 打印 Top-K 证据 + 引用。全程无模型下载、无 MySQL / Milvus。

``--real`` 路径（``real=True``）：懒加载 ``BGEM3Embedder`` / ``BGEReranker`` /
``MilvusStore``（仅此时才 import FlagEmbedding / pymilvus），检索 + 引用 + 打印。
这是生产脚手架；P2 阶段 Milvus 尚未通过 ``python -m app.rag`` 灌入真实数据，
故真实路径可能返回空结果（见代码内注释）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.rag.chunk import split_policy_markdown
from app.rag.citations import build_citations, render_citations
from app.rag.embedder import FakeEmbedder
from app.rag.reranker import FakeReranker
from app.rag.retrieval import Retriever

# 复用 app/rag/__main__.py 的 3 个政策文件路径与 content_type / root_category 映射。
KNOWLEDGE_DB = Path(__file__).resolve().parents[2] / "knowledge_db"
POLICY_FILES = [
    ("after-sales-manual.md", "manual", "售后政策"),
    ("returns-policy.md", "policy", "退款退货政策"),
    ("product-specifications.md", "manual", "商品规格手册"),
]


class _InMemoryStore:
    """与 brief 中 ``_Store`` 同形状的内存 store。

    ``hybrid_search`` 返回**全部**候选行（dummy score 仅作占位），
    真实排序交给 ``FakeReranker`` 完成——这是对语料全量的精排。
    """

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def upsert(self, records: list) -> None:
        self.rows.extend(records)

    def hybrid_search(self, dense, query_text: str, top_k: int) -> list[dict]:
        return [
            {"chunk_id": r["id"], "text": r["text"], "category": r["category"],
             "section_path": r["section_path"], "content_type": r["content_type"],
             "score": 0.8}
            for r in self.rows
        ]


def _load_fake_store() -> _InMemoryStore:
    """读取 3 个政策 md，切分 + ``FakeEmbedder`` 嵌入 + 写入内存 store。

    嵌入文本与 ``ingest_markdown`` 一致：``category + questions + answer``；
    合成顺序 ``id`` 仅是本地索引，不是伪造的业务数据。
    """
    embedder = FakeEmbedder(dim=8)
    store = _InMemoryStore()
    seq = 0
    for fname, ctype, root in POLICY_FILES:
        md = (KNOWLEDGE_DB / fname).read_text(encoding="utf-8")
        drafts = split_policy_markdown(md, content_type=ctype, root_category=root)
        texts = [f"{d.category} {d.questions} {d.answer}" for d in drafts]
        vectors = embedder.encode_dense(texts)
        for d, text, vec in zip(drafts, texts, vectors):
            seq += 1
            store.upsert([{
                "id": seq,
                "dense": vec,
                "text": text,
                "category": d.category,
                "section_path": d.section_path,
                "content_type": d.content_type,
            }])
    return store


def _print_result(chunks: list, evidence_confidence: float, passed: bool, top_k: int) -> None:
    """打印 Top-K 证据（片段）+ 渲染后的引用。"""
    top = chunks[:top_k]
    cites = build_citations(top)
    print(f"命中 {len(top)} 条证据（evidence_confidence={evidence_confidence:.3f}，passed={passed}）")
    for i, c in enumerate(top, start=1):
        print(f"\n[{i}] {c.section_path}（{c.content_type}）score={c.score:.3f}")
        print(f"    {c.snippet}")
    print("\n引用：")
    print(render_citations(cites))


def run(query: str, *, real: bool = False, top_k: int = 10) -> None:
    """执行检索并打印 Top-K 证据与引用（可测试核心）。"""
    if not real:
        store = _load_fake_store()
        retriever = Retriever(FakeEmbedder(dim=8), store, FakeReranker())
    else:
        # 生产路径脚手架：仅此处懒加载真实模型 + Milvus（避免触发模型下载 / pymilvus）。
        # 注意：P2 阶段 Milvus 尚未通过 ingest 灌入真实数据，此路径可能返回空结果。
        from app.config import settings
        from app.rag.bge import BGEM3Embedder, BGEReranker
        from app.rag.milvus_store import MilvusStore

        store = MilvusStore(settings.milvus_uri)
        store.ensure_collection()
        retriever = Retriever(BGEM3Embedder(), store, BGEReranker())

    res = retriever.retrieve(query, top_k=top_k)
    _print_result(res.chunks, res.evidence_confidence, res.passed, top_k)


def main(argv=None) -> None:
    """解析 argv：位置参数为查询文本，可选 ``--real``、``--top-k N``。"""
    args = list(sys.argv[1:] if argv is None else argv)
    real = False
    top_k = 10
    query_parts: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--real":
            real = True
        elif a == "--top-k":
            i += 1
            top_k = int(args[i])
        else:
            query_parts.append(a)
        i += 1

    query = " ".join(query_parts).strip()
    if not query:
        print('用法：python -m app.rag.search "查询文本" [--real] [--top-k N]', file=sys.stderr)
        sys.exit(2)
    run(query, real=real, top_k=top_k)


if __name__ == "__main__":
    main()

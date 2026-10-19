"""真实嵌入与精排：BGE-M3 + bge-reranker-v2-m3（FlagEmbedding，懒加载）。

导入本模块、构造实例均不 import FlagEmbedding / torch，也不下载或加载模型；
首次调用 ``encode_dense()`` / ``rerank()`` 时才延迟导入并实例化底层模型。

API 依据 FlagEmbedding v1.4.2 官方源码核实，见 dev-notes/ch06.md。
"""
from __future__ import annotations


class BGEM3Embedder:
    """BGE-M3 稠密嵌入器（封装 ``FlagEmbedding.BGEM3FlagModel``）。

    ``BGEM3FlagModel`` 实为 ``M3Embedder`` 的别名；``encode()`` 返回字典，
    稠密向量位于 ``["dense_vecs"]``（numpy.ndarray），bge-m3 稠密维度为 1024。
    """

    dim = 1024  # bge-m3 config.json hidden_size = 1024

    def __init__(self, model_name: str = "BAAI/bge-m3"):
        self.model_name = model_name
        self.model = None

    def encode_dense(self, texts: list[str]) -> list[list[float]]:
        if self.model is None:
            from FlagEmbedding import BGEM3FlagModel

            from app.config import settings

            self.model = BGEM3FlagModel(
                self.model_name,
                use_fp16=settings.embedding_use_fp16,
            )
        out = self.model.encode(
            texts,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        return out["dense_vecs"].tolist()


class BGEReranker:
    """bge-reranker-v2-m3 精排器（封装 ``FlagEmbedding.FlagReranker``）。

    ``FlagReranker`` 实为 ``BaseReranker`` 的别名；``compute_score()`` 接受
    ``[[query, passage], ...]`` 的句对列表，返回 ``list[float]``。

    ``normalize=True`` 对原始 logits 施加 sigmoid，使分数落在 0..1，
    与 ``FakeReranker`` 及检索闸（``compute_evidence_confidence``）的分母/阈值假设一致。
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        self.model_name = model_name
        self.model = None

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        if self.model is None:
            from FlagEmbedding import FlagReranker

            self.model = FlagReranker(self.model_name, normalize=True)
        pairs = [[query, passage] for passage in passages]
        return self.model.compute_score(pairs)

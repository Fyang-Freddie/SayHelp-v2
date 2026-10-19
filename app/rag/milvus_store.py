"""Milvus 向量库实现：collection + BM25 hybrid search + RRF。

API 均已按官方源码/实测核实（详见 dev-notes/ch06.md 的 "Task 5" 一节）：
  - pymilvus 3.0.2 ORM API（`pymilvus>=2.5` 目前解析到 3.0.2）：
      `Collection.hybrid_search(reqs, rerank, limit, ...)` 参数名为 `reqs=` / `rerank=`。
  - `AnnSearchRequest(data, anns_field, param, limit)`、`RRFRanker(k=60)`。
  - BM25 由 `Function(name, FunctionType.BM25, input_field_names=["text"],
    output_field_names=["sparse_vector"])` 从 `text` 生成 sparse 向量。
  - milvus-lite 3.2.2 实测支持 BM25 Function + SPARSE_INVERTED_INDEX +
    hybrid_search + RRF；但其内置分词器只有 `standard` / `jieba`，
    **不支持完整服务端的 `chinese`**，故默认用 `jieba`（中文分词，
    milvus-lite 需安装 `jieba` 包；完整服务端也可用）。
"""
from __future__ import annotations

import uuid

from pymilvus import (
    AnnSearchRequest,
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    Function,
    FunctionType,
    RRFRanker,
    connections,
    utility,
)

# milvus-lite 内置分词器名（走 analyzer_params 的 "tokenizer" 键）；
# 其余值（如 "chinese"）按完整服务端内建 analyzer（"type" 键）处理。
_TOKENIZER_ANALYZERS = {"standard", "jieba"}


class MilvusStore:
    """基于 Milvus（milvus-lite 或独立服务端）的 VectorStore 实现。

    analyzer_type：
      - "jieba"（默认）：中文分词，milvus-lite 与完整服务端都可用。
      - "standard"：空白/标点切分。
      - "chinese" 等：仅完整 Milvus 服务端内建 analyzer，milvus-lite 不支持。
    """

    def __init__(self, uri: str, collection_name: str = "sayhelp_knowledge",
                 analyzer_type: str = "jieba", dim: int = 1024) -> None:
        self.uri = uri
        self.collection_name = collection_name
        self.analyzer_type = analyzer_type
        self.dim = dim
        # 每个实例一个独立连接别名，避免重复 connect("default") 指向不同 uri 时互相污染。
        self._alias = f"milvus_{uuid.uuid4().hex}"
        self._col: Collection | None = None

    def _connect(self) -> None:
        connections.connect(alias=self._alias, uri=self.uri)

    def _analyzer_params(self) -> dict:
        if self.analyzer_type in _TOKENIZER_ANALYZERS:
            return {"tokenizer": self.analyzer_type}
        return {"type": self.analyzer_type}

    def ensure_collection(self) -> None:
        self._connect()
        if not utility.has_collection(self.collection_name, using=self._alias):
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535,
                            enable_analyzer=True, analyzer_params=self._analyzer_params()),
                FieldSchema(name="dense_vector", dtype=DataType.FLOAT_VECTOR, dim=self.dim),
                FieldSchema(name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR),
                FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="section_path", dtype=DataType.VARCHAR, max_length=512,
                            nullable=True),
                FieldSchema(name="content_type", dtype=DataType.VARCHAR, max_length=32,
                            nullable=True),
            ]
            schema = CollectionSchema(fields)
            schema.add_function(Function(
                name="bm25_text",
                function_type=FunctionType.BM25,
                input_field_names=["text"],
                output_field_names=["sparse_vector"],
            ))
            col = Collection(name=self.collection_name, schema=schema, using=self._alias)
            col.create_index(field_name="dense_vector",
                             index_params={"index_type": "FLAT", "metric_type": "COSINE"})
            col.create_index(field_name="sparse_vector",
                             index_params={"index_type": "SPARSE_INVERTED_INDEX",
                                           "metric_type": "BM25"})
        self._col = Collection(self.collection_name, using=self._alias)
        self._col.load()

    def upsert(self, records: list) -> None:
        if self._col is None:
            self.ensure_collection()
        rows = []
        for r in records:
            rows.append({
                "id": int(r["id"]),
                "text": r["text"],
                "dense_vector": [float(x) for x in r["dense"]],
                "category": r.get("category") or "",
                "section_path": r.get("section_path") or "",
                "content_type": r.get("content_type") or "",
            })
        self._col.upsert(rows)
        self._col.flush()

    def hybrid_search(self, dense_vec: list[float], query_text: str, top_k: int) -> list[dict]:
        if self._col is None:
            self.ensure_collection()
        dense_req = AnnSearchRequest(
            data=[dense_vec], anns_field="dense_vector",
            param={"metric_type": "COSINE", "params": {}}, limit=50)
        sparse_req = AnnSearchRequest(
            data=[query_text], anns_field="sparse_vector",
            param={"metric_type": "BM25"}, limit=50)
        res = self._col.hybrid_search(
            reqs=[dense_req, sparse_req], rerank=RRFRanker(), limit=top_k,
            output_fields=["id", "text", "category", "section_path", "content_type"])
        hits = res[0]
        return [
            {
                "chunk_id": h.id,
                "text": h.entity.get("text"),
                "category": h.entity.get("category"),
                "section_path": h.entity.get("section_path"),
                "content_type": h.entity.get("content_type"),
                "score": h.score,
            }
            for h in hits
        ]

    def close(self) -> None:
        connections.disconnect(self._alias)
        self._col = None

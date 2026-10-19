"""引用构建（citation 列表 + 渲染）。

`[n]` 编号从 1 连续递增，与传入 chunk 顺序一一对应；`render_citations` 每条引用
输出一行，绝不产生悬空编号或编号错位（Review Focus #5 引用可回溯）。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.rag.retrieval import ScoredChunk


@dataclass
class Citation:
    index: int
    chunk_id: object
    section_path: str
    category: str
    content_type: str
    snippet: str


def build_citations(chunks: list[ScoredChunk]) -> list[Citation]:
    """按输入顺序为每个 chunk 生成一条引用，编号从 1 连续递增。"""
    return [
        Citation(
            index=i,
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            category=chunk.category,
            content_type=chunk.content_type,
            snippet=chunk.snippet,
        )
        for i, chunk in enumerate(chunks, start=1)
    ]


def _text(value: object) -> str:
    return "" if value is None else str(value)


def render_citations(citations: list[Citation]) -> str:
    """每条引用一行：`[n] 章节路径（content_type）`，以换行连接。"""
    return "\n".join(
        f"[{c.index}] {_text(c.section_path)}（{_text(c.content_type)}）"
        for c in citations
    )

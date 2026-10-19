# SayHelp P2 — 知识入库与混合检索（Milvus / RRF / reranker / evidence_confidence / 引用）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task (user-selected execution method). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `knowledge_db/` 的真实政策/手册文本切分入库（MySQL `knowledge_chunks` ↔ Milvus 双写），并提供「dense(BGE-M3) + BM25(Milvus 中文分词) 混合检索 → RRF 融合 → bge-reranker-v2-m3 精排 → evidence_confidence 闸 → 引用构建」这条可独立验证的检索链路，供 P3 的 Agent 主链路调用。

**Architecture:** `app/rag/` 模块，职责分层：切分（纯函数）→ 嵌入/精排（`Embedder`/`Reranker` 协议 + 真实模型实现 + 测试假实现）→ 向量库（`VectorStore` 协议 + Milvus 实现 + 内存假实现）→ 检索编排（hybrid + RRF + rerank + Top-K）→ 置信度闸（纯函数）→ 引用（纯函数）。模型与向量库全部隔离在协议后，单元测试用确定性假实现，集成测试用 Milvus Lite（嵌入式、免 Docker）。

**Tech Stack:** Python 3.13.9、pymilvus≥2.5（hybrid/BM25/analyzer）、milvus-lite（测试）、FlagEmbedding≥1.3（BGE-M3 + bge-reranker-v2-m3，torch 后端）、SQLAlchemy 2.0、pytest。

**Spec:** `docs/superpowers/specs/2026-10-19-sayhelp-architecture.md`（§3.4 知识库、§6 知识入库与混合检索、§4.6 引用契约）。P2 只做「入库 + 检索 + 闸 + 引用」，不接 Agent/意图/Query 扩写/拒答入池（P3）。

## Global Constraints

- 语言：与用户中文沟通；代码/注释中文与英文混用，关键注释中文。
- Python 3.13.9（Anaconda `D:\anaconda\anaconda_files\python.exe`）；MySQL 8（Docker 3307）；Milvus 2.5 standalone（Docker，生产）/ milvus-lite（测试）。
- 红线（不可违反）：不伪造业务数据、不随机生成嵌入/检索结果（模型与库必须真实）；不冒充真人；`.env` 只提交 `.env.example`；**不伪造库接口**——pymilvus 2.5 的 `Function`/`hybrid_search`/`AnnSearchRequest`、FlagEmbedding 的 `BGEM3FlagModel`/`FlagReranker` 等确切 API 一律用 WebFetch 查官方文档核实后写入 `dev-notes/ch06.md`，未核实不得照抄记忆中的接口。
- 已锁定决策 D1–D8（其中 D5：BGE-M3 与 bge-reranker-v2-m3 本地自托管各一进程；D8：Milvus Docker 自托管）。
- 嵌入维度 = BGE-M3 的 1024；向量化文本 = `category + questions + answer` 拼接（§6）；政策用章节标题作 `questions`、上级标题路径作 `category`。
- `alembic.ini` 须 ASCII-only；索引名库内全局唯一；自增 PK 用 `BigIntPK`。P2 不新增表（复用 P0 的 `knowledge_chunks`），如需迁移用 alembic 补。
- 依赖版本兼容 Python 3.13：torch/transformers/pymilvus 版本在 Task 4 用官方文档核实；装不上时降级方案（onnxruntime 或 sentence-transformers）记录于 dev-notes。

## Review Focus

1. **切分忠实**：政策条款（`Axx`/`Rxx`）不得被拦腰截断或跨条款粘连；`Rxx` 的 `category` 必须含上级章路径（如「退款退货政策 > 第一章 基本定义」），`questions` 是条款标题、`answer` 是条款正文，不张冠李戴。
2. **入库幂等**：对同一批 md 连续跑两次 `ingest`，`knowledge_chunks` 与 Milvus 都不产生重复行/重复向量；`done` 的 chunk 不重复 embed。
3. **检索不越权也不漏**：`retrieve` 只返回真实入库的证据 chunk，且 Top-K 稳定可复现（同 query 同结果）；不返回 `pending`/未入库的 chunk。
4. **置信度闸诚实**：低相关（Top1 分低/证据少/Top1-Top2 分差小）→ `passed=False`，绝不因 spec 沉默而放行。
5. **引用可回溯**：`[n]` 编号与来源列表一一对应，每条含 `section_path`/`category`/`content_type`/`chunk_id`，不出现悬空编号或编号错位。

以上 5 类分别由 Task 1/3/5/6/7 的测试钉住。

---

### Task 1: 知识切分（标题层级感知 chunker）

**Files:**
- Create: `app/rag/__init__.py`
- Create: `app/rag/chunk.py`
- Test: `tests/test_rag_chunk.py`

**Interfaces:**
- Consumes: 无（纯函数，不依赖外部）。
- Produces:
  - `app.rag.chunk.ChunkDraft`（`@dataclass`：`category: str`、`questions: str`、`answer: str`、`section_path: str | None`、`content_type: str`、`is_key_clause: bool`）
  - `app.rag.chunk.split_policy_markdown(md_text: str, *, content_type: str, root_category: str) -> list[ChunkDraft]`

**规则（§6）**：按标题层级切分。`### ` 条款成块（`questions`=标题、`answer`=正文、`category`=root+上级章、`section_path`=root+章+条款）；`## ` 无 `### ` 子项的平铺文档成块（`category`=root）；`## ` 有 `### ` 子项为「章」，仅作分组路径（正文为章节导语时单独成块）；`# `(H1) 与前置版本说明块（blockquote）忽略；`【】` 标题 `is_key_clause=True`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_rag_chunk.py
from app.rag.chunk import split_policy_markdown


FLAT_MD = """# 售后政策

> 版本：AS-2026.10

## A01【售后类型】
售后服务包括：补发、维修、换货、部分退款、退货退款、仅退款以及平台争议处理。

## A02【售后起算时间】
需要以收货为起点的服务，原则上以物流签收时间为依据。
"""

TWO_LEVEL_MD = """# 退款退货政策

## 第一章 基本定义

### R01【退款】
退款是指交易款项全部或部分退回买家。

### R02【退货退款】
退货退款是指买家将已收到的商品退回。
"""


def test_split_flat_clauses():
    chunks = split_policy_markdown(FLAT_MD, content_type="manual", root_category="售后政策")
    assert [c.questions for c in chunks] == ["A01【售后类型】", "A02【售后起算时间】"]
    assert chunks[0].answer.startswith("售后服务包括")
    assert chunks[0].section_path == "售后政策 > A01【售后类型】"
    assert chunks[0].category == "售后政策"
    assert chunks[0].content_type == "manual"
    assert chunks[0].is_key_clause is True


def test_split_two_level_chapter_path_in_category():
    chunks = split_policy_markdown(TWO_LEVEL_MD, content_type="policy", root_category="退款退货政策")
    # 章（无正文）不单独成块，只产生两个 R 条款
    assert [c.questions for c in chunks] == ["R01【退款】", "R02【退货退款】"]
    assert chunks[0].category == "退款退货政策 > 第一章 基本定义"
    assert chunks[0].section_path == "退款退货政策 > 第一章 基本定义 > R01【退款】"


def test_chapter_preamble_emits_own_chunk():
    md = "# 退款退货政策\n\n## 第一章 基本定义\n本章定义退款与退货退款两类基础概念。\n\n### R01【退款】\n退款是指款项退回。\n"
    chunks = split_policy_markdown(md, content_type="policy", root_category="退款退货政策")
    questions = [c.questions for c in chunks]
    assert "第一章 基本定义" in questions and "R01【退款】" in questions


def test_split_skips_front_matter_and_h1():
    md = "# 标题\n\n> 版本说明\n\n## A01【售后类型】\n正文。\n"
    chunks = split_policy_markdown(md, content_type="manual", root_category="售后政策")
    assert len(chunks) == 1
    assert chunks[0].questions == "A01【售后类型】"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `D:/anaconda/anaconda_files/python.exe -m pytest tests/test_rag_chunk.py -v`
Expected: FAIL（`ModuleNotFoundError: app.rag.chunk` 或 `ImportError`）

- [ ] **Step 3: 实现切分**

```python
# app/rag/chunk.py
from dataclasses import dataclass


@dataclass
class ChunkDraft:
    category: str
    questions: str
    answer: str
    section_path: str | None
    content_type: str
    is_key_clause: bool


def _heading_level(line: str) -> tuple[int, str] | None:
    """返回 (层级, 标题)；仅 ## 与 ### 参与切分，H1(# )作文档标题忽略。"""
    if line.startswith("### "):
        return 3, line[4:].strip()
    if line.startswith("## "):
        return 2, line[3:].strip()
    return None


def split_policy_markdown(md_text: str, *, content_type: str, root_category: str) -> list[ChunkDraft]:
    # 1) 按标题切段：[(level, title, body_lines)]，正文与前置 blockquote 自然留在段外被丢弃
    lines = md_text.splitlines()
    sections: list[tuple[int, str, list[str]]] = []
    current: tuple[int, str, list[str]] | None = None
    for line in lines:
        heading = _heading_level(line)
        if heading is not None:
            if current is not None:
                sections.append(current)
            current = (heading[0], heading[1], [])
        elif current is not None:
            current[2].append(line)
    if current is not None:
        sections.append(current)

    # 2) 判定每个 ## 段是「章」还是「平铺条款」：紧跟其后的段是 ### 即为章
    has_child = [False] * len(sections)
    for i in range(len(sections) - 1):
        if sections[i][0] == 2 and sections[i + 1][0] == 3:
            has_child[i] = True

    # 3) 生成 chunk
    chunks: list[ChunkDraft] = []
    chapter_title: str | None = None
    for i, (level, title, body) in enumerate(sections):
        body_text = "\n".join(body).strip()
        if level == 2:
            if has_child[i]:
                # 章：仅作分组路径；若有正文（章节导语）单独成块
                chapter_title = title
                if body_text:
                    chunks.append(ChunkDraft(
                        category=root_category, questions=title, answer=body_text,
                        section_path=f"{root_category} > {title}",
                        content_type=content_type,
                        is_key_clause=("【" in title and "】" in title),
                    ))
                continue
            # 平铺条款（无 ### 子项）
            chapter_title = None
            if not body_text:
                continue
            chunks.append(ChunkDraft(
                category=root_category, questions=title, answer=body_text,
                section_path=f"{root_category} > {title}",
                content_type=content_type,
                is_key_clause=("【" in title and "】" in title),
            ))
        else:  # level == 3
            if not body_text:
                continue
            cat = f"{root_category} > {chapter_title}" if chapter_title else root_category
            sp = f"{root_category} > {chapter_title} > {title}" if chapter_title else f"{root_category} > {title}"
            chunks.append(ChunkDraft(
                category=cat, questions=title, answer=body_text, section_path=sp,
                content_type=content_type,
                is_key_clause=("【" in title and "】" in title),
            ))
    return chunks
```

- [ ] **Step 4: 运行测试确认通过**

Run: `D:/anaconda/anaconda_files/python.exe -m pytest tests/test_rag_chunk.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/rag/__init__.py app/rag/chunk.py tests/test_rag_chunk.py
git commit -m "feat(p2): title-structure-aware knowledge chunker"
```

---

### Task 2: Embedder / Reranker 协议 + 确定性假实现

**Files:**
- Create: `app/rag/embedder.py`
- Create: `app/rag/reranker.py`
- Test: `tests/test_rag_fakes.py`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `Embedder`（`typing.Protocol`）：`dim: int`；`encode_dense(self, texts: list[str]) -> list[list[float]]`
  - `Reranker`（`Protocol`）：`rerank(self, query: str, passages: list[str]) -> list[float]`（长度与 passages 对齐，值越大越相关）
  - `app.rag.embedder.FakeEmbedder(dim: int = 8)`：确定性向量——`text` 每个 char 的 `ord` 累加进固定维度，保证同 text 同向量、不同 text 一般不同向量。
  - `app.rag.reranker.FakeReranker`：确定性分数——按 `passage` 与 `query` 的字符重叠度给出 `0..1` 分数。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_rag_fakes.py
from app.rag.embedder import FakeEmbedder
from app.rag.reranker import FakeReranker


def test_fake_embedder_deterministic_and_shaped():
    e = FakeEmbedder(dim=8)
    v1 = e.encode_dense(["手机保修多久"])
    assert len(v1) == 1 and len(v1[0]) == 8
    assert v1 == e.encode_dense(["手机保修多久"])  # 确定性
    assert v1[0] != e.encode_dense(["退款规则"])[0]


def test_fake_reranker_scores_by_overlap():
    r = FakeReranker()
    q = "手机保修多久"
    scores = r.rerank(q, ["手机保修 12 个月", "退货退款运费谁出", "手机保修多久"])
    assert scores[2] > scores[0] > scores[1]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `D:/anaconda/anaconda_files/python.exe -m pytest tests/test_rag_fakes.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现协议与假实现**

```python
# app/rag/embedder.py
from typing import Protocol


class Embedder(Protocol):
    dim: int

    def encode_dense(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    def __init__(self, dim: int = 8):
        self.dim = dim

    def encode_dense(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * self.dim
            for i, ch in enumerate(t):
                vec[i % self.dim] += ord(ch)
            out.append(vec)
        return out
```

```python
# app/rag/reranker.py
from typing import Protocol


class Reranker(Protocol):
    def rerank(self, query: str, passages: list[str]) -> list[float]: ...


class FakeReranker:
    def rerank(self, query: str, passages: list[str]) -> list[float]:
        q = set(query)
        scores = []
        for p in passages:
            if not p:
                scores.append(0.0)
                continue
            overlap = sum(1 for ch in set(p) if ch in q)
            scores.append(min(1.0, overlap / max(len(q), 1)))
        return scores
```

- [ ] **Step 4: 运行测试确认通过**

Run: `D:/anaconda/anaconda_files/python.exe -m pytest tests/test_rag_fakes.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/rag/embedder.py app/rag/reranker.py tests/test_rag_fakes.py
git commit -m "feat(p2): Embedder/Reranker protocols + deterministic fakes"
```

---

### Task 3: 入库流水线（MySQL 双写 + 幂等）

**Files:**
- Create: `app/rag/ingest.py`
- Create: `app/rag/__main__.py`
- Test: `tests/test_rag_ingest.py`

**Interfaces:**
- Consumes: `split_policy_markdown`/`ChunkDraft`（Task 1）；`Embedder`（Task 2）；`KnowledgeChunk`（P0 模型）；`Session`（`app.db`）。
- Produces:
  - `app.rag.ingest.ingest_markdown(session, *, md_text, content_type, root_category, embedder: Embedder, vector_store) -> dict`（返回 `{"inserted": int, "vectorized": int, "skipped": int}`）
  - `app.rag.__main__`：CLI `python -m app.rag`（从 `knowledge_db/` 读取 after-sales-manual.md / returns-policy.md / product-specifications.md，跑入库）

**规则（§6 双写）**：先写 MySQL `knowledge_chunks`（`vectorize_status=pending`）→ 对 pending 行 `embedder.encode_dense` → `vector_store.upsert`（稳定主键=chunk.id）→ 回填 `vector_id=str(chunk.id)` + `vectorize_status=done`。幂等：`done` 行跳过；重跑/中断不重复 embed（只处理 pending）。`vector_store` 用 `typing.Protocol` 最小接口（本任务只需 `upsert(records)`），真实 Milvus 在 Task 5 接。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_rag_ingest.py
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
```

> 注：本测试用真实 sqlite（conftest 的 `db_session`），嵌入/向量库用假实现——验证的是「双写顺序 + 幂等 + 状态回填」，不是模型。

- [ ] **Step 2: 运行测试确认失败**

Run: `D:/anaconda/anaconda_files/python.exe -m pytest tests/test_rag_ingest.py -v`
Expected: FAIL（`ModuleNotFoundError: app.rag.ingest`）

- [ ] **Step 3: 实现入库**

```python
# app/rag/ingest.py
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
    new_drafts = [d for d in drafts if (d.category, d.questions) not in existing]
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
```

```python
# app/rag/__main__.py
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `D:/anaconda/anaconda_files/python.exe -m pytest tests/test_rag_ingest.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/rag/ingest.py app/rag/__main__.py tests/test_rag_ingest.py
git commit -m "feat(p2): idempotent MySQL knowledge ingestion pipeline"
```

---

### Task 4: 真实嵌入与精排（BGE-M3 + bge-reranker-v2-m3，FlagEmbedding）

**Files:**
- Create: `app/rag/bge.py`
- Modify: `app/config.py`（新增 `embedding_model`、`reranker_model`、`embedding_use_fp16` 等模型配置）
- Modify: `requirements.txt`（`FlagEmbedding>=1.3`）
- Test: `tests/test_rag_bge.py`

**Interfaces:**
- Consumes: `Embedder`/`Reranker` 协议（Task 2）；`settings`。
- Produces:
  - `app.rag.bge.BGEM3Embedder(model_name="BAAI/bge-m3")`：`dim = 1024`；`encode_dense` 用 `BGEM3FlagModel.encode(...)["dense_vecs"]`
  - `app.rag.bge.BGEReranker(model_name="BAAI/bge-reranker-v2-m3")`：`rerank` 用 `FlagReranker.compute_score([[q, p], ...])`

**规则（红线·不伪造接口）**：`BGEM3FlagModel` / `FlagReranker` 的确切构造参数与返回值结构（`dense_vecs` 字段名、`compute_score` 入参形状）必须用 WebFetch 查 FlagEmbedding 官方 README（github.com/FlagOpen/FlagEmbedding）核实后写入 `dev-notes/ch06.md`；不按记忆照抄。模型首次调用自动从 HuggingFace 下载（国内可配 `HF_ENDPOINT=https://hf-mirror.com`）。测试**只验证协议满足 + 懒加载不崩**，不触发真实下载：

```python
# tests/test_rag_bge.py
from app.rag.bge import BGEM3Embedder, BGEReranker


def test_bge3_embedder_declares_dim_1024():
    e = BGEM3Embedder()
    assert e.dim == 1024


def test_reranker_is_lazy():
    r = BGEReranker()
    assert r.model is None  # 未触发下载
```

- [ ] **Step 1: 写失败测试**（如上面两个）
- [ ] **Step 2: 运行确认失败**（`ModuleNotFoundError: app.rag.bge`）
- [ ] **Step 3: 实现**（懒加载模型，`__init__` 只存模型名，首次 `encode_dense`/`rerank` 才实例化；API 按 WebFetch 核实结果写）
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `feat(p2): real BGE-M3 embedder + bge-reranker-v2-m3 (lazy)`

> 依赖安装为一次性动作：`D:/anaconda/anaconda_files/python.exe -m pip install "FlagEmbedding>=1.3"`。若 torch/transformers 在 Python 3.13 装不上，执行者停下报告（不可擅自换模型），由我裁定降级方案（onnxruntime BGE-M3 或 sentence-transformers）。

---

### Task 5: Milvus 向量库（collection + hybrid_search + RRF）

**Files:**
- Create: `app/rag/milvus_store.py`
- Modify: `requirements.txt`（`pymilvus>=2.5`、`milvus-lite>=2.5`）
- Test: `tests/test_rag_milvus_store.py`（用 milvus-lite 临时文件）

**Interfaces:**
- Consumes: `VectorStore` 协议（Task 3 定义的 `upsert`）；`settings.milvus_uri`。
- Produces:
  - `app.rag.milvus_store.MilvusStore(uri, collection_name="sayhelp_knowledge")`：`ensure_collection()`、`upsert(records)`、`hybrid_search(dense_vec, query_text, top_k) -> list[dict]`
  - `hybrid_search` 返回的 dict 键：`chunk_id`、`text`、`category`、`section_path`、`content_type`、`score`（`ScoredChunk` 由 Task 6 的 `retrieval.py` 定义并从这些 dict 转换）。

**Schema**：`id`(INT64 主键=chunk.id)、`text`(VARCHAR, `enable_analyzer=True`, `analyzer_params={"type": "chinese"}`)、`dense_vector`(FLOAT_VECTOR, dim=1024)、`sparse_vector`(SPARSE_FLOAT_VECTOR, 由 BM25 `Function` 从 `text` 生成)、`category`/`section_path`/`content_type`(VARCHAR)。检索 = `AnnSearchRequest`(dense, Top-50) + `AnnSearchRequest`(text→sparse, Top-50) → `hybrid_search(..., rerank=RRFRanker(), limit=top_k)`。

> `Function`/`AnnSearchRequest`/`hybrid_search`/`RRFRanker` 的确切参数名与调用序必须 WebFetch 查 pymilvus 官方文档（milvus.io 或 github.com/milvus-io/pymilvus）核实，写入 `dev-notes/ch06.md`；milvus-lite 是否支持 BM25 `Function` 一并核实——若 milvus-lite 不支持，本任务的集成测试改用「dense-only + Python RRF」这条降级路径，并在计划裁定记录。

- [ ] **Step 1: 写失败测试**（用 milvus-lite：`MilvusStore("sayhelp_test.db")` → `ensure_collection` → `upsert` 3 条 1024 维向量 → `hybrid_search` 断言返回 Top-1 命中正确 chunk 且分数降序；结束后删临时文件）
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `feat(p2): Milvus store with BM25 hybrid search + RRF`

---

### Task 6: 检索编排 + evidence_confidence 闸

**Files:**
- Create: `app/rag/retrieval.py`
- Modify: `app/config.py`（新增 `rerank_min`、`evidence_confidence_threshold` 检索阈值配置）
- Test: `tests/test_rag_retrieval.py`、`tests/test_rag_gate.py`

**Interfaces:**
- Consumes: `Embedder`（Task 2）、`VectorStore.hybrid_search -> list[dict]`（Task 5）、`Reranker`（Task 2）、`settings` 阈值。
- Produces:
  - `app.rag.retrieval.ScoredChunk`（`@dataclass`：`chunk_id`、`score`、`category`、`section_path`、`content_type`、`snippet`）
  - `app.rag.retrieval.Retriever(embedder, store, reranker)`：`retrieve(query: str, top_k: int = 10) -> RetrievalResult`
  - `app.rag.retrieval.compute_evidence_confidence(top1_score: float, evidence_count: int, margin: float) -> float`（`0..1`）
  - `app.rag.retrieval.passes_gate(confidence: float) -> bool`（`confidence >= settings.evidence_confidence_threshold`）

**`RetrievalResult`**（`@dataclass`）：`chunks: list[ScoredChunk]`、`evidence_confidence: float`、`passed: bool`。

**闸（§6，阈值待标注集校准）**：`evidence_confidence = 0.5*clamp(top1_score/0.6) + 0.3*min(evidence_count/3, 1) + 0.2*clamp(margin/0.15)`；`passed = evidence_confidence >= settings.evidence_confidence_threshold`（默认 0.5）。Top-K 中 rerank 分数 ≥ `settings.rerank_min`（默认 0.3）的视为有效证据计入 `evidence_count`；`margin = top1 - top2`（证据不足 2 条时 margin 取 0）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_rag_gate.py
from app.rag.retrieval import compute_evidence_confidence, passes_gate


def test_low_top1_fails_gate():
    c = compute_evidence_confidence(top1_score=0.1, evidence_count=1, margin=0.01)
    assert not passes_gate(c)


def test_strong_evidence_passes():
    c = compute_evidence_confidence(top1_score=0.9, evidence_count=3, margin=0.3)
    assert passes_gate(c)


def test_margin_and_count_matter():
    hi = compute_evidence_confidence(0.5, 3, 0.3)
    lo = compute_evidence_confidence(0.5, 1, 0.01)
    assert hi > lo
```

```python
# tests/test_rag_retrieval.py
from app.rag.embedder import FakeEmbedder
from app.rag.reranker import FakeReranker
from app.rag.retrieval import Retriever


class _Store:
    def hybrid_search(self, dense, query_text, top_k):
        return [
            {"chunk_id": 3, "text": "手机保修多久 手机保修 12 个月", "category": "售后政策", "section_path": "售后政策 > A06", "content_type": "manual", "score": 0.9},
            {"chunk_id": 2, "text": "七天无理由退换货规则", "category": "售后政策", "section_path": "售后政策 > A03", "content_type": "manual", "score": 0.5},
            {"chunk_id": 1, "text": "运费承担 退货", "category": "退款退货政策", "section_path": "退款退货政策 > R31", "content_type": "policy", "score": 0.1},
        ]


def test_retrieve_reranks_and_gates():
    r = Retriever(FakeEmbedder(dim=8), _Store(), FakeReranker())
    res = r.retrieve("手机保修多久", top_k=3)
    assert res.chunks[0].chunk_id == 3  # 精排后最相关在前
    assert res.chunks[0].snippet  # 非空摘要
    assert res.evidence_confidence >= 0.0
    assert isinstance(res.passed, bool)
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**（`ScoredChunk`/`RetrievalResult` 用 `dataclasses`；`retrieve` = embed → hybrid_search → rerank → 排序 → 闸；dict → `ScoredChunk` 转换时 `snippet = text[:80]`）
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `feat(p2): retrieval orchestration + evidence_confidence gate`

---

### Task 7: 引用构建（citation 列表 + 渲染）

**Files:**
- Create: `app/rag/citations.py`
- Test: `tests/test_rag_citations.py`

**Interfaces:**
- Consumes: `ScoredChunk`（Task 6）。
- Produces:
  - `app.rag.citations.Citation`（`@dataclass`：`index`、`chunk_id`、`section_path`、`category`、`content_type`、`snippet`）
  - `app.rag.citations.build_citations(chunks: list[ScoredChunk]) -> list[Citation]`
  - `app.rag.citations.render_citations(citations: list[Citation]) -> str`（每行 `[n] 章节路径（content_type）`）

**规则（§6）**：编号从 1 连续递增，与传入 chunk 顺序一一对应；`render_citations` 输出不含悬空编号。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_rag_citations.py
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
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `feat(p2): citation list building + rendering`

---

### Task 8: 端到端检索 CLI（`python -m app.rag.search`）

**Files:**
- Create: `app/rag/search.py`（`__main__`）
- Test: `tests/test_rag_e2e.py`（用假模型 + 内存 store，验证「切分→入库→检索→引用」串通）

**Interfaces:**
- Consumes: Task 3 `ingest_markdown`、Task 6 `Retriever`、Task 7 `build_citations`。
- Produces: `python -m app.rag.search "查询文本"` 打印 Top-K 证据 + 引用（真实模型路径：`--real` 用 `BGEM3Embedder`/`MilvusStore`，默认用假实现以便无模型/无 Milvus 时也能跑通演示）。

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**（`search.py`：`main()` 组装 pipeline 并打印；`--real` 分支懒加载真实模型 + Milvus）
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `feat(p2): end-to-end retrieval CLI`

---

## 完成验收（P2）

- `python -m pytest` 全套通过（含新增 rag 测试，全部用假模型/假库，无网络/无模型下载依赖）。
- `python -m app.rag` 能把三个政策 md 灌入 MySQL `knowledge_chunks`（`vectorize_status=done`），重跑幂等。
- `python -m app.rag.search "手机保修多久"`（默认假实现）能打印 Top-K 证据与引用，端到端串通。
- 真实模型路径（`--real` + Milvus standalone）作为生产路径提供，首次运行下载模型/建 collection；其 API 与版本兼容性已按官方文档核实并记录 `dev-notes/ch06.md`。

# SayHelp P0 — 工程骨架、数据模型与真实数据导入 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可运行的工程底座：git 仓库、配置、18 张权威表的 SQLAlchemy 模型与 Alembic 迁移，并把 `knowledge_db/` 四份真实业务数据（订单/物流/商品主数据/退款原因）解析导入 MySQL，同时落种子账号（admin/agent/26 位客户）。

**Architecture:** 单一 FastAPI 应用包 `app/`，pydantic-settings 从 `.env` 读配置；SQLAlchemy 2.0 声明式模型分模块存放；纯函数 Markdown 解析器（`app/ingest/parsers.py`）与 ORM 解耦，可无 DB 单测；种子脚本幂等。迁移用 Alembic，权威库 MySQL（InnoDB/utf8mb4）。

**Tech Stack:** Python 3.13 · SQLAlchemy 2.0 · pymysql · pydantic-settings · Alembic · bcrypt · pytest · Docker(MySQL 8, 端口 3307)。

**Spec:** `docs/superpowers/specs/2026-10-19-sayhelp-architecture.md`（§3 数据模型 DDL 是模型与迁移的唯一依据）。

## Global Constraints

- Python 3.13；MySQL 统一 InnoDB + utf8mb4；连接 `DATABASE_URL=mysql+pymysql://...@127.0.0.1:3307/sayhelp`。
- `knowledge_db/` 与 `sft_dataset/` 是**只读真实数据**，任何代码不得写入或修改它们；读取一律显式 `encoding="utf-8"`。
- 不伪造业务数据；导入结果必须与源文件逐条一致（条数/字段/金额/时间/枚举）。
- `.env` 含真实密钥，**不提交**；只提交 `.env.example`（全部占位）。
- 金额用 `Decimal`，时间用 `datetime`；虚拟商品 `签收时间` 解析为 `NULL`（源文件“不适用”）。

## Review Focus

1. **金额与时间解析**：`"139.00"`→`Decimal("139.00")`；`"不适用"`→`None`；`"2026-09-24 06:31:27"`→`datetime`。任何一处把 `"不适用"` 当时间或丢失小数位都会污染业务数据。→ Task 4 测试。
2. **多商品项物流**：运单的 `商品项ID` 是 `"ITEM00001、ITEM00002"`（顿号分隔）整体字符串，不得拆开或当单值。→ Task 4 测试。
3. **种子幂等**：重跑 seed 业务表结果一致（快照覆盖），用户表不重置已存在账号密码。→ Task 5 测试。
4. **编码**：源文件为 UTF-8；Windows 控制台默认 GBK，读取必须显式 `encoding="utf-8"`，否则中文乱码。→ Task 4 测试。
5. **商品“主数据索引”表边界**：`product-specifications.md` 首表是 40 行主数据，其后是“详细规格”bullet 段，解析器只取首表，不得把详细规格误当行。→ Task 4 测试。

---

## File Structure

```
sayhelp/
├── .gitignore
├── requirements.txt / requirements-dev.txt
├── .env.example
├── docker-compose.yml            # MySQL 8（P0；Milvus/Langfuse 后续阶段加）
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/0001_initial.py
├── app/
│   ├── __init__.py
│   ├── config.py                 # pydantic-settings
│   ├── db.py                     # engine / SessionLocal / Base
│   ├── models/
│   │   ├── __init__.py           # 汇总导出 + Base.metadata
│   │   ├── base.py               # DeclarativeBase
│   │   ├── auth.py               # User
│   │   ├── business.py           # Order/Product/Logistics/RefundReason
│   │   ├── conversation.py       # Conversation/Message/RetrievalSnapshot
│   │   ├── knowledge.py          # KnowledgeChunk/QaExtractionStaging/ConversationSummary
│   │   └── flywheel.py           # Ticket/ToolAuditLog/LowConfidenceQuestion/ReviewQueueItem/FaithCase/EvalRun/TopicClassification
│   └── ingest/
│       ├── __init__.py
│       ├── markdown_table.py     # 通用 Markdown 表格解析
│       ├── parsers.py            # orders/logistics/products/refund_reasons 解析
│       └── seed.py               # 建账号 + 导入业务数据
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_models.py
    ├── test_markdown_table.py
    ├── test_parsers.py
    └── test_seed.py
```

---

### Task 1: 工程骨架、依赖与配置

**Files:**
- Create: `.gitignore`, `requirements.txt`, `requirements-dev.txt`, `.env.example`, `app/__init__.py`, `app/config.py`, `app/db.py`, `tests/conftest.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `app.config.settings`（含 `database_url` 等全部字段）；`app.db.Base`、`app.db.engine`、`app.db.SessionLocal`、`app.db.get_db`；`tests/conftest.py` 提供 `PROJECT_ROOT` fixture。

- [ ] **Step 1: 初始化 git 仓库与目录**

```bash
cd D:/llm_agent/sayhelp
git init
mkdir -p app/models app/ingest tests alembic/versions
```

- [ ] **Step 2: 写 `.gitignore`**

```gitignore
__pycache__/
*.pyc
.venv/
venv/
.env
.pytest_cache/
.mypy_cache/
*.egg-info/
log/
```

- [ ] **Step 3: 写依赖文件**

`requirements.txt`:
```
sqlalchemy>=2.0.30,<2.1
pymysql>=1.1.1
pydantic>=2.7
pydantic-settings>=2.3
alembic>=1.13
bcrypt>=4.1
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest>=8.2
```

- [ ] **Step 4: 写 `.env.example`（全占位，无真实密钥）**

```ini
# --- MySQL ---
MYSQL_DATABASE=sayhelp
MYSQL_USER=sayhelp
MYSQL_PASSWORD=CHANGE_ME
MYSQL_ROOT_PASSWORD=CHANGE_ME_ROOT
MYSQL_PORT=3307
DATABASE_URL=mysql+pymysql://sayhelp:CHANGE_ME@127.0.0.1:3307/sayhelp?charset=utf8mb4
TEST_DATABASE_URL=mysql+pymysql://root:CHANGE_ME_ROOT@127.0.0.1:3307/mysql?charset=utf8mb4

# --- 主力模型（OpenAI 兼容） ---
CHAT_BASE_URL=https://api.deepseek.com/v1
CHAT_MODEL=deepseek-flash
CHAT_API_KEY=CHANGE_ME
MODEL_PROVIDER_CONTEXT_WINDOW=1000000

# --- jev 意图模型（待用户提供端点） ---
JEV_MODEL=jev-1.13.0
JEV_BASE_URL=CHANGE_ME
JEV_API_KEY=CHANGE_ME

# --- Milvus ---
MILVUS_URI=http://127.0.0.1:19530
MILVUS_TOKEN=
MILVUS_MINIO_USER=CHANGE_ME
MILVUS_MINIO_PASSWORD=CHANGE_ME

# --- Langfuse（自部署） ---
LANGFUSE_HOST=http://127.0.0.1:3000
LANGFUSE_PUBLIC_KEY=CHANGE_ME
LANGFUSE_SECRET_KEY=CHANGE_ME
```

- [ ] **Step 5: 写 `app/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str
    test_database_url: str | None = None

    chat_base_url: str = ""
    chat_model: str = ""
    chat_api_key: str = ""
    model_provider_context_window: int = 1000000

    jev_model: str = ""
    jev_base_url: str = ""
    jev_api_key: str = ""

    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_token: str = ""
    milvus_minio_user: str = ""
    milvus_minio_password: str = ""

    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""


settings = Settings()
```

- [ ] **Step 6: 写 `app/db.py` 与 `app/__init__.py`**

```python
# app/__init__.py
```

```python
# app/db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 7: 写 `tests/conftest.py` 与 `tests/test_config.py`**

```python
# tests/conftest.py
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT
```

```python
# tests/test_config.py
from app.config import settings


def test_settings_loads_database_url():
    assert settings.database_url.startswith("mysql+pymysql://")


def test_settings_have_model_fields():
    assert isinstance(settings.chat_model, str)
    assert isinstance(settings.jev_model, str)
```

- [ ] **Step 8: 安装依赖并跑测试**

```bash
cd D:/llm_agent/sayhelp
python -m pip install -r requirements-dev.txt
python -m pytest tests/test_config.py -v
```
Expected: PASS（2 项，依赖 `.env` 已存在）。

- [ ] **Step 9: Commit**

```bash
git add .gitignore requirements.txt requirements-dev.txt .env.example app/ tests/
git commit -m "chore: scaffold project, config, db session"
```

---

### Task 2: SQLAlchemy 全量模型（18 张表）

**Files:**
- Create: `app/models/base.py`, `app/models/auth.py`, `app/models/business.py`, `app/models/conversation.py`, `app/models/knowledge.py`, `app/models/flywheel.py`, `app/models/__init__.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `app.db.Base`
- Produces: 模型类 `User/Order/Product/Logistics/RefundReason/Conversation/Message/RetrievalSnapshot/KnowledgeChunk/QaExtractionStaging/ConversationSummary/Ticket/ToolAuditLog/LowConfidenceQuestion/ReviewQueueItem/FaithCase/EvalRun/TopicClassification`；`app.models.Base.metadata`（含全部表）。

- [ ] **Step 1: 写 `app/models/base.py`**

```python
from app.db import Base

__all__ = ["Base"]
```

- [ ] **Step 2: 写 `app/models/auth.py`**

```python
import enum

from sqlalchemy import BigInteger, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserRole(str, enum.Enum):
    customer = "customer"
    agent = "agent"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), default=UserRole.customer, nullable=False)
    customer_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime, server_default=func.now(), nullable=False)
```

- [ ] **Step 3: 写 `app/models/business.py`**（照 Spec §3.2 DDL 逐字段）

```python
from decimal import Decimal
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, DECIMAL, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    order_no: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    item_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    product_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_spec: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    order_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    sign_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    order_status: Mapped[str] = mapped_column(String(32), nullable=False)
    after_sale_status: Mapped[str] = mapped_column(String(32), default="无售后", nullable=False)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    model: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    order_spec: Mapped[str] = mapped_column(String(128), nullable=False)
    product_type: Mapped[str] = mapped_column(String(64), nullable=False)
    seven_day_return: Mapped[str] = mapped_column(String(128), nullable=False)
    warranty: Mapped[str] = mapped_column(String(128), nullable=False)


class Logistics(Base):
    __tablename__ = "logistics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    item_ids: Mapped[str] = mapped_column(String(128), nullable=False)
    waybill_no: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    logistics_type: Mapped[str] = mapped_column(String(16), nullable=False)
    carrier: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    latest_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_latest: Mapped[bool] = mapped_column(default=True, nullable=False)
    trajectory: Mapped[str] = mapped_column(String(1024), nullable=False)


class RefundReason(Base):
    __tablename__ = "refund_reasons"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
```

- [ ] **Step 4: 写 `app/models/conversation.py`、`knowledge.py`、`flywheel.py`**

（内容照 Spec §3.3–3.5 的 DDL 逐字段翻译；关键约束：`ConversationSummary` 有 `UniqueConstraint("conversation_id", "seq")`；`LowConfidenceQuestion.matched_review_id` 外键指向 `review_queue.id` 且 `ondelete="SET NULL"`；`KnowledgeChunk.prev_chunk_id/next_chunk_id` 自引用 `ondelete="SET NULL"`；`ToolAuditLog` 不挂任何外键；`FaithCase.eval_id` 唯一；`Ticket.ticket_no` 主键 + `idempotency_key` 唯一。）

> 注：`LowConfidenceQuestion` 引用 `ReviewQueueItem`，二者需在同一 metadata 内定义；把 `review_queue` 表放在 `flywheel.py` 且在 `LowConfidenceQuestion` 之前定义即可。

- [ ] **Step 5: 写 `app/models/__init__.py` 汇总导出**

```python
from app.models.auth import User
from app.models.business import Logistics, Order, Product, RefundReason
from app.models.conversation import Conversation, Message, RetrievalSnapshot
from app.models.knowledge import ConversationSummary, KnowledgeChunk, QaExtractionStaging
from app.models.flywheel import (
    EvalRun, FaithCase, LowConfidenceQuestion, ReviewQueueItem,
    Ticket, ToolAuditLog, TopicClassification,
)
from app.db import Base

__all__ = [
    "Base", "User", "Order", "Product", "Logistics", "RefundReason",
    "Conversation", "Message", "RetrievalSnapshot", "KnowledgeChunk",
    "QaExtractionStaging", "ConversationSummary", "Ticket", "ToolAuditLog",
    "LowConfidenceQuestion", "ReviewQueueItem", "FaithCase", "EvalRun",
    "TopicClassification",
]
```

- [ ] **Step 6: 写 `tests/test_models.py`（SQLite 内存校验表结构，无需 MySQL）**

```python
import sqlalchemy as sa
from sqlalchemy import create_engine

from app.db import Base


def test_all_tables_present():
    from app import models  # noqa: F401  触发全部模型注册
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    names = set(sa.inspect(engine).get_table_names())
    expected = {
        "users", "orders", "products", "logistics", "refund_reasons",
        "conversations", "messages", "retrieval_snapshots",
        "knowledge_chunks", "qa_extraction_staging", "conversation_summaries",
        "tickets", "tool_audit_logs", "low_confidence_questions",
        "review_queue", "faith_cases", "eval_runs", "topic_classifications",
    }
    assert expected <= names


def test_low_confidence_matched_review_fk_set_null():
    from app.models import LowConfidenceQuestion
    fks = {c.name: c for c in LowConfidenceQuestion.__table__.constraints if isinstance(c, sa.ForeignKeyConstraint)}
    for cols in fks.values():
        for fk in cols.elements:
            if fk.column.table.name == "review_queue":
                assert fk.ondelete == "SET NULL"
```

- [ ] **Step 7: 运行测试**

```bash
python -m pytest tests/test_models.py -v
```
Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add app/models/ tests/test_models.py
git commit -m "feat: SQLAlchemy models for all 18 authoritative tables"
```

---

### Task 3: 通用 Markdown 表格解析器

**Files:**
- Create: `app/ingest/__init__.py`, `app/ingest/markdown_table.py`
- Test: `tests/test_markdown_table.py`

**Interfaces:**
- Produces: `parse_markdown_table(text: str) -> tuple[list[str], list[list[str]]] | None`（返回首表 `(headers, rows)`，单元格已 strip，跳过对齐分隔行；无表返回 None）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_markdown_table.py
from app.ingest.markdown_table import parse_markdown_table

SAMPLE = """\
# 标题
| a | b | c |
|---|---|---|
| 1 | 2 | 3 |
| 4 | 5 | 6 |

不属于表格的段落
"""


def test_parses_first_table():
    headers, rows = parse_markdown_table(SAMPLE)
    assert headers == ["a", "b", "c"]
    assert rows == [["1", "2", "3"], ["4", "5", "6"]]


def test_skips_alignment_separator():
    text = "| x | y |\n|:---|---:|\n| a | b |\n"
    headers, rows = parse_markdown_table(text)
    assert headers == ["x", "y"]
    assert rows == [["a", "b"]]


def test_no_table_returns_none():
    assert parse_markdown_table("只有文字，没有表格。") is None


def test_ignores_after_table_ends():
    text = "| a |\n|---|\n| 1 |\n\n后续非表格内容\n| 假 |\n"
    headers, rows = parse_markdown_table(text)
    assert headers == ["a"]
    assert rows == [["1"]]
```

- [ ] **Step 2: 运行确认失败**

```bash
python -m pytest tests/test_markdown_table.py -v
```
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

```python
# app/ingest/markdown_table.py
import re

_SEPARATOR_CELL = re.compile(r":?-{2,}:?")


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_SEPARATOR_CELL.fullmatch(c) for c in cells)


def parse_markdown_table(text: str) -> tuple[list[str], list[list[str]]] | None:
    headers: list[str] | None = None
    rows: list[list[str]] = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            if headers is not None:
                break  # 表格结束后的非表格行
            continue
        cells = _split_row(s)
        if _is_separator(cells):
            continue
        if headers is None:
            headers = cells
        else:
            rows.append(cells)
    if headers is None:
        return None
    return headers, rows
```

- [ ] **Step 4: 运行确认通过**

```bash
python -m pytest tests/test_markdown_table.py -v
```
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add app/ingest/ tests/test_markdown_table.py
git commit -m "feat: generic markdown table parser"
```

---

### Task 4: 业务数据解析器（orders/logistics/products/refund_reasons）

**Files:**
- Create: `app/ingest/parsers.py`
- Test: `tests/test_parsers.py`

**Interfaces:**
- Consumes: `parse_markdown_table`
- Produces:
  - `parse_orders(md_text: str) -> list[dict]` — keys: `customer_id, order_no, item_id, product_name, model_spec, quantity, paid_amount, order_time, sign_time, order_status, after_sale_status`
  - `parse_logistics(md_text: str) -> list[dict]` — keys: `order_no, item_ids, waybill_no, logistics_type, carrier, status, latest_time, is_latest, trajectory`
  - `parse_products(md_text: str) -> list[dict]` — keys: `product_name, model, order_spec, product_type, seven_day_return, warranty`
  - `parse_refund_reasons(md_text: str) -> list[dict]` — keys: `code, display_name`

- [ ] **Step 1: 写失败测试（针对真实文件，锁定条数与关键值）**

```python
# tests/test_parsers.py
from datetime import datetime
from decimal import Decimal

from app.ingest.parsers import (
    parse_logistics, parse_orders, parse_products, parse_refund_reasons,
)


def _read(project_root, name):
    return (project_root / "knowledge_db" / name).read_text(encoding="utf-8")


def test_parse_orders_counts_and_key_values(project_root):
    orders = parse_orders(_read(project_root, "orders.md"))
    assert len(orders) == 100
    assert len({o["order_no"] for o in orders}) == 82
    assert len({o["customer_id"] for o in orders}) == 26
    first = orders[0]
    assert first["customer_id"] == "C0016"
    assert first["order_no"] == "TB202611000001"
    assert first["item_id"] == "ITEM00001"
    assert first["paid_amount"] == Decimal("139.00")
    assert first["order_time"] == datetime(2026, 9, 24, 6, 31, 27)


def test_parse_orders_virtual_goods_sign_time_none(project_root):
    orders = parse_orders(_read(project_root, "orders.md"))
    virtual = {o["item_id"]: o for o in orders}
    assert virtual["ITEM00037"]["sign_time"] is None  # 软件激活码
    assert virtual["ITEM00038"]["sign_time"] is None  # 在线课程兑换码
    assert virtual["ITEM00001"]["sign_time"] == datetime(2026, 9, 27, 7, 45, 49)


def test_parse_logistics_counts_and_multi_item(project_root):
    rows = parse_logistics(_read(project_root, "logistics.md"))
    assert len(rows) == 200
    assert rows[0]["item_ids"] == "ITEM00001、ITEM00002"  # 顿号整体保留
    assert rows[0]["is_latest"] is False
    latest = [r for r in rows if r["is_latest"]]
    assert len(latest) == 88  # 每运单一条最新


def test_parse_products_only_index_table(project_root):
    products = parse_products(_read(project_root, "product-specifications.md"))
    assert len(products) == 40
    assert products[0]["model"] == "MM-E100"
    assert all(p["model"].startswith("MM-") for p in products)


def test_parse_refund_reasons_counts(project_root):
    reasons = parse_refund_reasons(_read(project_root, "refund-reasons.md"))
    assert len(reasons) == 50
    assert reasons[0] == {"code": "no_longer_needed", "display_name": "不想要了"}
    assert reasons[-1]["code"] == "other"
```

- [ ] **Step 2: 运行确认失败**

```bash
python -m pytest tests/test_parsers.py -v
```
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现解析器**

```python
# app/ingest/parsers.py
from datetime import datetime
from decimal import Decimal

from app.ingest.markdown_table import parse_markdown_table

_TS = "%Y-%m-%d %H:%M:%S"


def _dt(s: str) -> datetime | None:
    s = s.strip()
    if s == "" or s == "不适用":
        return None
    return datetime.strptime(s, _TS)


def parse_orders(md_text: str) -> list[dict]:
    _, rows = parse_markdown_table(md_text) or ([], [])
    out = []
    for r in rows:
        out.append({
            "customer_id": r[0],
            "order_no": r[1],
            "item_id": r[2],
            "product_name": r[3],
            "model_spec": r[4],
            "quantity": int(r[5]),
            "paid_amount": Decimal(r[6]),
            "order_time": datetime.strptime(r[7], _TS),
            "sign_time": _dt(r[8]),
            "order_status": r[9],
            "after_sale_status": r[10],
        })
    return out


def parse_logistics(md_text: str) -> list[dict]:
    _, rows = parse_markdown_table(md_text) or ([], [])
    out = []
    for r in rows:
        out.append({
            "order_no": r[0],
            "item_ids": r[1],
            "waybill_no": r[2],
            "logistics_type": r[3],
            "carrier": r[4],
            "status": r[5],
            "latest_time": datetime.strptime(r[6], _TS),
            "is_latest": r[7] == "是",
            "trajectory": r[8],
        })
    return out


def parse_products(md_text: str) -> list[dict]:
    _, rows = parse_markdown_table(md_text) or ([], [])
    return [{
        "product_name": r[0], "model": r[1], "order_spec": r[2],
        "product_type": r[3], "seven_day_return": r[4], "warranty": r[5],
    } for r in rows]


def parse_refund_reasons(md_text: str) -> list[dict]:
    _, rows = parse_markdown_table(md_text) or ([], [])
    return [{"code": r[0], "display_name": r[1]} for r in rows]
```

- [ ] **Step 4: 运行确认通过**

```bash
python -m pytest tests/test_parsers.py -v
```
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add app/ingest/parsers.py tests/test_parsers.py
git commit -m "feat: parse real business data (orders/logistics/products/reasons)"
```

---

### Task 5: 种子脚本（账号 + 业务数据导入，幂等）

**Files:**
- Create: `app/ingest/seed.py`
- Test: `tests/test_seed.py`

**Interfaces:**
- Consumes: `parse_orders/parse_logistics/parse_products/parse_refund_reasons`, `app.models.*`, `SessionLocal`
- Produces: `seed_all(session) -> dict`（返回各表导入条数，便于断言/日志）；`ADMIN_USERNAME`, `AGENT_USERNAME`, `DEFAULT_PASSWORD` 常量。

- [ ] **Step 1: 写失败测试（SQLite 内存，验证幂等与归属映射）**

```python
# tests/test_seed.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.ingest import seed
from app.models import Order, User


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_seed_business_counts():
    s = _session()
    report = seed.seed_all(s)
    assert report["orders"] == 100
    assert report["logistics"] == 200
    assert report["products"] == 40
    assert report["refund_reasons"] == 50


def test_seed_creates_users_per_customer():
    s = _session()
    seed.seed_all(s)
    customers = s.query(User).filter(User.role == "customer").all()
    assert len(customers) == 26
    ids = {c.customer_id for c in customers}
    assert "C0001" in ids and "C0030" in ids and "C0009" not in ids


def test_seed_idempotent_and_preserves_password():
    s = _session()
    seed.seed_all(s)
    admin = s.query(User).filter(User.username == seed.ADMIN_USERNAME).one()
    admin.password_hash = "custom_hash"
    s.commit()
    seed.seed_all(s)  # 重跑
    admin2 = s.query(User).filter(User.username == seed.ADMIN_USERNAME).one()
    assert admin2.password_hash == "custom_hash"  # 不重置已有账号
    assert s.query(Order).count() == 100       # 业务表仍是快照总数，不翻倍
```

- [ ] **Step 2: 运行确认失败**

```bash
python -m pytest tests/test_seed.py -v
```
Expected: FAIL（`seed` 模块不存在）。

- [ ] **Step 3: 实现 `app/ingest/seed.py`**

```python
import bcrypt
from pathlib import Path

from sqlalchemy.orm import Session

from app.ingest.parsers import (
    parse_logistics, parse_orders, parse_products, parse_refund_reasons,
)
from app.models import (
    Logistics, Order, Product, RefundReason, User, UserRole,
)

KNOWLEDGE_DB = Path(__file__).resolve().parents[2] / "knowledge_db"

ADMIN_USERNAME = "admin"
AGENT_USERNAME = "agent"
DEFAULT_PASSWORD = "SayHelp123!"  # 仅开发种子，见 .env.example


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _seed_users(session: Session, customer_ids: set[str]) -> int:
    existing = {u.username for u in session.query(User.username).all()}
    to_add = []
    if ADMIN_USERNAME not in existing:
        to_add.append(User(username=ADMIN_USERNAME, password_hash=_hash(DEFAULT_PASSWORD),
                           role=UserRole.admin))
    if AGENT_USERNAME not in existing:
        to_add.append(User(username=AGENT_USERNAME, password_hash=_hash(DEFAULT_PASSWORD),
                           role=UserRole.agent, display_name="坐席 王小明"))
    for cid in sorted(customer_ids):
        uname = f"cust_{cid.lower()}"
        if uname not in existing:
            to_add.append(User(username=uname, password_hash=_hash(DEFAULT_PASSWORD),
                               role=UserRole.customer, customer_id=cid))
    session.add_all(to_add)
    return len(to_add)


def _reset_business(session: Session) -> None:
    for model in (Logistics, Order, Product, RefundReason):
        session.query(model).delete()


def seed_all(session: Session) -> dict:
    orders = parse_orders((KNOWLEDGE_DB / "orders.md").read_text(encoding="utf-8"))
    logistics = parse_logistics((KNOWLEDGE_DB / "logistics.md").read_text(encoding="utf-8"))
    products = parse_products((KNOWLEDGE_DB / "product-specifications.md").read_text(encoding="utf-8"))
    reasons = parse_refund_reasons((KNOWLEDGE_DB / "refund-reasons.md").read_text(encoding="utf-8"))

    customer_ids = {o["customer_id"] for o in orders}
    new_users = _seed_users(session, customer_ids)

    _reset_business(session)
    session.add_all([Order(**o) for o in orders])
    session.add_all([Logistics(**l) for l in logistics])
    session.add_all([Product(**p) for p in products])
    session.add_all([RefundReason(**r) for r in reasons])
    session.commit()

    return {
        "orders": len(orders), "logistics": len(logistics),
        "products": len(products), "refund_reasons": len(reasons),
        "new_users": new_users,
    }
```

- [ ] **Step 4: 运行确认通过**

```bash
python -m pytest tests/test_seed.py -v
```
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add app/ingest/seed.py tests/test_seed.py
git commit -m "feat: idempotent seed for users and business data"
```

---

### Task 6: Alembic 迁移与 docker-compose MySQL

**Files:**
- Create: `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial.py`, `docker-compose.yml`, `app/ingest/__main__.py`

**Interfaces:**
- Produces: `python -m app.ingest` 命令（运行 seed 到真实 MySQL）；`docker compose up -d mysql` 起库；`alembic upgrade head` 建表。

- [ ] **Step 1: 写 `docker-compose.yml`**

```yaml
services:
  mysql:
    image: mysql:8.0
    container_name: sayhelp-mysql
    environment:
      MYSQL_DATABASE: ${MYSQL_DATABASE:-sayhelp}
      MYSQL_USER: ${MYSQL_USER:-sayhelp}
      MYSQL_PASSWORD: ${MYSQL_PASSWORD}
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
    ports:
      - "${MYSQL_PORT:-3307}:3306"
    command: --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
    volumes:
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-p${MYSQL_ROOT_PASSWORD}"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  mysql_data:
```

- [ ] **Step 2: 写 `alembic.ini` 与 `alembic/env.py`**

`alembic.ini`（关键行）：
```ini
[alembic]
script_location = alembic
sqlalchemy.url = mysql+pymysql://sayhelp:CHANGE_ME@127.0.0.1:3307/sayhelp?charset=utf8mb4
```

`alembic/env.py`（要点：从 `app.config.settings.database_url` 取 URL，`target_metadata = Base.metadata`，并 `from app import models` 触发注册）：
```python
from alembic import context
from sqlalchemy import create_engine, pool

from app.config import settings
from app.db import Base
from app import models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"),
                      target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(config.get_main_option("sqlalchemy.url"), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: 生成初始迁移 `0001_initial.py`**

```bash
cd D:/llm_agent/sayhelp
python -m alembic revision --autogenerate -m "initial schema"
```
（需先起 MySQL；未起时此步延后，但脚本骨架与命令已就位。生成后人工核对：外键 `ON DELETE SET NULL`、`review_queue` 先于 `low_confidence_questions` 建、`tool_audit_logs` 无外键。）

- [ ] **Step 4: 写 `app/ingest/__main__.py`（命令行 seed 入口）**

```python
from app.db import SessionLocal
from app.ingest.seed import seed_all

if __name__ == "__main__":
    with SessionLocal() as session:
        report = seed_all(session)
        print("seed report:", report)
```

- [ ] **Step 5: 验证（需 Docker Desktop 已启动）**

```bash
docker compose up -d mysql
python -m alembic upgrade head
python -m app.ingest
```
Expected: 输出 `orders=100, logistics=200, products=40, refund_reasons=50, new_users=28`（admin+agent+26 客户）。

- [ ] **Step 6: Commit**

```bash
git add alembic.ini alembic/ docker-compose.yml app/ingest/__main__.py
git commit -m "chore: alembic migrations and docker-compose mysql"
```

---

### Task 7: 集成验证（可选，需 Docker）

**Files:** 无新增；验证现有命令与数据。

- [ ] **Step 1: 起 MySQL 并跑 seed，核对行数**

```bash
docker compose up -d mysql
python -m alembic upgrade head
python -m app.ingest
```

- [ ] **Step 2: 用 mysql 客户端抽查数据一致性**

```bash
docker exec -it sayhelp-mysql mysql -usayhelp -p -D sayhelp \
  -e "SELECT COUNT(*) FROM orders; SELECT COUNT(*) FROM logistics; SELECT COUNT(*) FROM products; SELECT COUNT(*) FROM refund_reasons; SELECT COUNT(*) FROM users;"
```
Expected: `100 / 200 / 40 / 50 / 28`。

- [ ] **Step 3: 核对“不适用”签收时间为 NULL**

```bash
docker exec -it sayhelp-mysql mysql -usayhelp -p -D sayhelp \
  -e "SELECT item_id, sign_time FROM orders WHERE item_id IN ('ITEM00037','ITEM00038');"
```
Expected: `sign_time` 均为 `NULL`。

- [ ] **Step 4: Commit（如有脚本调整）**

```bash
git add -A && git commit -m "chore: verify seed against live MySQL"
```

---

## Self-Review 结论

- **Spec 覆盖**：P0 覆盖 Spec §3（数据模型）+ 现状清单的数据导入；§4 及之后（契约/工作流/检索/上下文/飞轮/sft）属 P1–P8，不在本计划范围。
- **占位扫描**：无 TBD/TODO；Task 6 的 `0001_initial.py` 由 autogenerate 生成（依赖 Docker，已在 Step 3 标注延后条件，非占位）。
- **类型一致**：解析器 key 与 `Order(**o)` 等构造参数一一对应；`seed_all` 返回 dict 的键在测试中一致引用。
- **Review Focus**：5 项失败模式分别对应 Task 4（金额/时间、多商品项、编码、商品索引边界）与 Task 5（幂等）的测试。

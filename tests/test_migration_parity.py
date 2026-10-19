"""迁移 ↔ 模型 一致性测试。

把 Base.metadata 按 MySQL 方言编译成 (CREATE TABLE + CREATE INDEX) 语句集，
与冻结迁移 0001_initial.py 里存储的语句集做全量相等比较。任何漂移——索引、
DEFAULT 子句、类型、ON UPDATE、外键语义——都会使该测试失败。
"""
import importlib.util
from pathlib import Path

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

import app.models  # noqa: F401  触发全部模型注册
from app.db import Base

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0001_initial.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0001", MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _metadata_statements() -> list[str]:
    dialect = mysql.dialect()
    stmts: list[str] = []
    for table in Base.metadata.sorted_tables:
        stmts.append(str(CreateTable(table).compile(dialect=dialect)).strip())
        for ix in sorted(table.indexes, key=lambda i: i.name):
            stmts.append(str(CreateIndex(ix).compile(dialect=dialect)).strip())
    return sorted(stmts)


def _migration_statements() -> list[str]:
    mod = _load_migration()
    stmts = [ddl.strip() for _, ddl in mod._TABLES_UP]
    stmts += [ddl.strip() for ddl in getattr(mod, "_INDEXES_UP", [])]
    return sorted(stmts)


def test_migration_matches_model_metadata():
    expected = _metadata_statements()
    actual = _migration_statements()

    missing = [s for s in expected if s not in actual]
    extra = [s for s in actual if s not in expected]
    assert not missing and not extra, (
        f"迁移与模型漂移。缺少 {len(missing)} 条、多出 {len(extra)} 条。\n"
        f"--- 迁移缺少 ---\n" + "\n".join(missing) +
        f"\n--- 迁移多出 ---\n" + "\n".join(extra)
    )


def test_migration_has_on_update_clauses():
    # 规格 §3.3/3.4/3.5 要求三个表的 updated_at 有 ON UPDATE CURRENT_TIMESTAMP。
    # SQLAlchemy 的 MySQL 方言不渲染该子句，故迁移用显式 ALTER 语句补齐；
    # 期望值从 metadata 独立推导，迁移必须与之一致。
    expected = [
        f"ALTER TABLE {t.name} MODIFY updated_at DATETIME NOT NULL "
        f"DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
        for t in Base.metadata.sorted_tables
        if "updated_at" in t.columns
    ]
    actual = [s.strip() for s in getattr(_load_migration(), "_ON_UPDATE", [])]

    assert set(actual) == set(expected), (
        f"ON UPDATE 子句漂移。\n期望({len(expected)}): {sorted(expected)}\n"
        f"实际({len(actual)}): {sorted(actual)}"
    )

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

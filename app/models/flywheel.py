import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text,
    func, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, BigIntPK


def _values(e: type[enum.Enum]) -> list[str]:
    return [m.value for m in e]


class ToolSource(str, enum.Enum):
    builtin = "builtin"
    mcp = "mcp"


class ToolStatus(str, enum.Enum):
    success = "成功"
    failure = "失败"
    timeout = "超时"
    validation_blocked = "校验拦下"
    permission_denied = "权限拒绝"


class ReviewStatus(str, enum.Enum):
    pending = "待审"
    approved = "通过"
    rejected = "驳回"


class LowConfidenceSource(str, enum.Enum):
    retrieval_low_conf = "retrieval_low_conf"
    self_check = "self_check"
    user_feedback = "user_feedback"


class FaithCaseStatus(str, enum.Enum):
    unresolved = "未解决"
    resolved = "已解决"
    no_resolution_needed = "无需解决"


class EvalTrigger(str, enum.Enum):
    scheduled = "定时"
    manual = "手动"


class Ticket(Base):
    __tablename__ = "tickets"

    ticket_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", server_default="open", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class ToolAuditLog(Base):
    __tablename__ = "tool_audit_logs"
    __table_args__ = (
        Index("idx_conversation_id", "conversation_id"),
        Index("idx_tool_name", "tool_name"),
        Index("idx_tool_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_source: Mapped[ToolSource] = mapped_column(
        Enum(ToolSource, name="tool_source", values_callable=_values), nullable=False
    )
    mcp_server: Mapped[str | None] = mapped_column(String(64), nullable=True)
    arguments: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ToolStatus] = mapped_column(
        Enum(ToolStatus, name="tool_status", values_callable=_values), nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class ReviewQueueItem(Base):
    __tablename__ = "review_queue"
    __table_args__ = (Index("idx_review_status", "review_status"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    normalized_question: Mapped[str] = mapped_column(String(512), nullable=False)
    ai_suggested_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), nullable=False)
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status", values_callable=_values),
        default=ReviewStatus.pending, server_default="待审", nullable=False,
    )
    approved_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LowConfidenceQuestion(Base):
    __tablename__ = "low_confidence_questions"
    __table_args__ = (
        Index("idx_source", "source"),
        Index("idx_created_at", "created_at"),
        Index("idx_matched_review_id", "matched_review_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("conversations.id"), nullable=True
    )
    raw_question: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[LowConfidenceSource] = mapped_column(
        Enum(LowConfidenceSource, name="low_confidence_source", values_callable=_values),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_chunks: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    matched_review_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("review_queue.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class FaithCase(Base):
    __tablename__ = "faith_cases"
    __table_args__ = (
        Index("idx_faith_status", "status"),
        Index("idx_last_seen_at", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    eval_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    bucket: Mapped[str] = mapped_column(String(24), nullable=False)
    query: Mapped[str] = mapped_column(String(512), nullable=False)
    strategy: Mapped[str] = mapped_column(
        String(24), default="hybrid_rerank", server_default="hybrid_rerank", nullable=False
    )
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    judge_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[FaithCaseStatus] = mapped_column(
        Enum(FaithCaseStatus, name="faith_case_status", values_callable=_values),
        default=FaithCaseStatus.unresolved, server_default="未解决", nullable=False,
    )
    seen_count: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    resolution: Mapped[str | None] = mapped_column(String(300), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EvalRun(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (Index("idx_eval_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    triggered_by: Mapped[EvalTrigger] = mapped_column(
        Enum(EvalTrigger, name="eval_trigger", values_callable=_values),
        default=EvalTrigger.scheduled, server_default="定时", nullable=False,
    )
    dataset_size: Mapped[int] = mapped_column(Integer, nullable=False)
    eval_set: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class TopicClassification(Base):
    __tablename__ = "topic_classifications"
    __table_args__ = (Index("idx_lcq", "low_confidence_question_id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    low_confidence_question_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    labels: Mapped[list] = mapped_column(JSON, nullable=False)
    classified_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

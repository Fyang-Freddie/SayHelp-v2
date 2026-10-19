import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger, DateTime, Enum, ForeignKey, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class VectorizeStatus(str, enum.Enum):
    pending = "pending"
    done = "done"


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    questions: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    section_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_key_clause: Mapped[bool] = mapped_column(default=False, nullable=False)
    prev_chunk_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("knowledge_chunks.id", ondelete="SET NULL"), nullable=True
    )
    next_chunk_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("knowledge_chunks.id", ondelete="SET NULL"), nullable=True
    )
    vector_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vectorize_status: Mapped[VectorizeStatus] = mapped_column(
        Enum(VectorizeStatus, name="vectorize_status"), default=VectorizeStatus.pending, index=True, nullable=False
    )
    doc_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    doc_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    doc_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class QaExtractionStatus(str, enum.Enum):
    extracted = "extracted"
    kept = "kept"
    discarded = "discarded"


class QaExtractionStaging(Base):
    __tablename__ = "qa_extraction_staging"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_no: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[QaExtractionStatus] = mapped_column(
        Enum(QaExtractionStatus, name="qa_extraction_status"),
        default=QaExtractionStatus.extracted, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"
    __table_args__ = (UniqueConstraint("conversation_id", "seq", name="uk_conv_seq"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    from_msg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    upto_msg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

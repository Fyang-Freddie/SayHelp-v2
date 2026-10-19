import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, DECIMAL, Enum, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    tool = "tool"
    system = "system"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_upto_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    layer1_from_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole, name="message_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_calls: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    citations: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    feedback: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class RetrievalSnapshot(Base):
    __tablename__ = "retrieval_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    user_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    answer_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence_confidence: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

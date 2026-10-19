import enum

from sqlalchemy import DateTime, Enum, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, BigIntPK


class UserRole(str, enum.Enum):
    customer = "customer"
    agent = "agent"
    admin = "admin"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("idx_customer_id", "customer_id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        default=UserRole.customer, server_default="customer", nullable=False,
    )
    customer_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("1"), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime, server_default=func.now(), nullable=False)

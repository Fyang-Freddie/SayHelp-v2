from decimal import Decimal
from datetime import datetime

from sqlalchemy import DateTime, DECIMAL, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, BigIntPK


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("idx_customer", "customer_id"),
        Index("idx_order", "order_no"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(16), nullable=False)
    order_no: Mapped[str] = mapped_column(String(32), nullable=False)
    item_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    product_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_spec: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    order_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    sign_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    order_status: Mapped[str] = mapped_column(String(32), nullable=False)
    after_sale_status: Mapped[str] = mapped_column(
        String(32), default="无售后", server_default="无售后", nullable=False
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (Index("idx_name", "product_name"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    product_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    order_spec: Mapped[str] = mapped_column(String(128), nullable=False)
    product_type: Mapped[str] = mapped_column(String(64), nullable=False)
    seven_day_return: Mapped[str] = mapped_column(String(128), nullable=False)
    warranty: Mapped[str] = mapped_column(String(128), nullable=False)


class Logistics(Base):
    __tablename__ = "logistics"
    __table_args__ = (
        Index("idx_logistics_order", "order_no"),
        Index("idx_waybill", "waybill_no"),
        Index("idx_latest", "is_latest"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(32), nullable=False)
    item_ids: Mapped[str] = mapped_column(String(128), nullable=False)
    waybill_no: Mapped[str] = mapped_column(String(32), nullable=False)
    logistics_type: Mapped[str] = mapped_column(String(16), nullable=False)
    carrier: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    latest_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_latest: Mapped[bool] = mapped_column(default=True, server_default=text("1"), nullable=False)
    trajectory: Mapped[str] = mapped_column(Text, nullable=False)


class RefundReason(Base):
    __tablename__ = "refund_reasons"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)

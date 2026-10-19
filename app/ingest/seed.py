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

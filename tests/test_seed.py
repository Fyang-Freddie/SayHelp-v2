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

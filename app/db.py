from sqlalchemy import BigInteger, Integer, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


# MySQL 用 BIGINT 主键；SQLite 只有 INTEGER PRIMARY KEY 会自增，
# 故在 SQLite 方言下降级为 INTEGER，保证内存库测试可自增主键。
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

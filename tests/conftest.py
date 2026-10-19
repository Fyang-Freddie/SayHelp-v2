from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.db import Base, get_db
from app.models import (  # noqa: F401  注册全部模型到 Base.metadata
    Conversation,
    Message,
    User,
    UserRole,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


def create_test_app() -> FastAPI:
    """Task 2 专用最小应用：只挂 auth 路由 + 测试库。Task 5 合并进 app.main 后删除。"""
    from app.api.auth import router as auth_router
    from app.api.chat import router as chat_router
    from app.api.conversations import router as conversations_router
    from app.auth.deps import require_role

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(conversations_router)
    app.include_router(chat_router)

    # require_role 在 P1 尚无真实端点，挂一条一次性受保护路由用于 403 断言。
    @app.get("/api/auth/_test/agent-only")
    def agent_only(user: User = Depends(require_role("agent"))):
        return {"ok": True}

    return app


@pytest.fixture()
def db_session():
    # 内存 SQLite + StaticPool：所有请求共享同一个连接，即同一份数据库。
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db_session):
    app = create_test_app()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def user_factory(db_session):
    """创建并持久化一个 User 的工厂；Tasks 3/4/6 复用。"""

    def _make(
        username="customer1",
        password="SayHelp123!",
        role=UserRole.customer,
        is_active=True,
        **kwargs,
    ) -> User:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
            **kwargs,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _make


@pytest.fixture()
def user_a(user_factory):
    return user_factory(username="user_a")


@pytest.fixture()
def user_b(user_factory):
    return user_factory(username="user_b")


@pytest.fixture()
def conv_a(db_session, user_a):
    conv = Conversation(user_id=user_a.id)
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)
    return conv


@pytest.fixture()
def conv_b(db_session, user_b):
    conv = Conversation(user_id=user_b.id)
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)
    return conv


@pytest.fixture()
def msg_a(db_session, conv_a):
    msg = Message(conversation_id=conv_a.id, role="user", content="hello")
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)
    return msg


@pytest.fixture()
def conv_a_with_10_messages(db_session, user_a):
    conv = Conversation(user_id=user_a.id)
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)
    for i in range(10):
        db_session.add(
            Message(
                conversation_id=conv.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"msg-{i}",
            )
        )
    db_session.commit()
    return conv

"""Settings 校验：JWT 密钥不得静默使用开发默认值（fail-fast 硬化）。"""
import pytest
from pydantic import ValidationError

from app.config import Settings

DEFAULT_SECRET = "dev-secret-change-me"


def test_settings_rejects_default_jwt_secret(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("JWT_SECRET", DEFAULT_SECRET)
    with pytest.raises(ValidationError):
        Settings()


def test_settings_accepts_custom_jwt_secret(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("JWT_SECRET", "a-sufficiently-random-secret")
    assert Settings().jwt_secret == "a-sufficiently-random-secret"

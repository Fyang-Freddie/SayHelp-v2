import pytest
import jwt
from app.auth.security import (
    create_access_token, decode_access_token, hash_password, verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("SayHelp123!")
    assert hashed != "SayHelp123!"
    assert verify_password("SayHelp123!", hashed)
    assert not verify_password("wrong", hashed)


def test_password_hash_is_bcrypt():
    assert hash_password("x").startswith("$2")


def test_token_roundtrip_carries_sub_and_role():
    token = create_access_token(user_id=7, role="customer")
    payload = decode_access_token(token)
    assert payload["sub"] == "7"
    assert payload["role"] == "customer"


def test_token_rejects_tampering():
    token = create_access_token(user_id=7, role="customer")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token + "x")

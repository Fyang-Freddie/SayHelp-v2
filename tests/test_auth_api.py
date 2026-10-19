import pytest


@pytest.fixture()
def user(user_factory):
    return user_factory(username="customer1", customer_id="C001", display_name="测试客户")


@pytest.fixture()
def inactive_user(user_factory):
    return user_factory(username="blocked1", is_active=False)


def _login(client, username, password="SayHelp123!"):
    return client.post("/api/auth/login", data={"username": username, "password": password})


def test_login_returns_token_and_user(client, user):
    resp = _login(client, "customer1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["id"] == user.id
    assert body["user"]["username"] == "customer1"
    assert body["user"]["role"] == "customer"
    assert body["user"]["is_active"] is True
    assert body["user"]["created_at"]


def test_login_wrong_password_401(client, user):
    resp = _login(client, "customer1", password="wrong-password")
    assert resp.status_code == 401


def test_login_inactive_403(client, inactive_user):
    resp = _login(client, "blocked1")
    assert resp.status_code == 403


def test_me_without_token_401(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_valid_token_200(client, user):
    token = _login(client, "customer1").json()["access_token"]
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "customer1"


def test_me_with_forged_token_401(client):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_require_role_wrong_role_403(client, user):
    token = _login(client, "customer1").json()["access_token"]
    resp = client.get("/api/auth/_test/agent-only", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403

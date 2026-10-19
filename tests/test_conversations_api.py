def _auth(client, username="user_a"):
    token = client.post(
        "/api/auth/login",
        data={"username": username, "password": "SayHelp123!"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_list_only_own_conversations(client, user_a, user_b, conv_a, conv_b):
    headers = _auth(client, "user_a")
    resp = client.get("/api/conversations", headers=headers)
    assert resp.status_code == 200
    ids = [c["id"] for c in resp.json()]
    assert conv_a.id in ids
    assert conv_b.id not in ids


def test_create_conversation(client, user_a):
    headers = _auth(client, "user_a")
    resp = client.post("/api/conversations", headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"]
    assert body["status"] == "open"
    assert body["created_at"]
    assert body["updated_at"]


def test_cannot_read_others_messages(client, user_a, conv_b):
    headers = _auth(client, "user_a")
    resp = client.get(f"/api/conversations/{conv_b.id}/messages", headers=headers)
    assert resp.status_code == 404


def test_messages_paginated_ascending(client, user_a, conv_a_with_10_messages):
    headers = _auth(client, "user_a")
    resp = client.get(
        f"/api/conversations/{conv_a_with_10_messages.id}/messages?limit=3&offset=3",
        headers=headers,
    )
    assert resp.status_code == 200
    assert [m["id"] for m in resp.json()] == [4, 5, 6]

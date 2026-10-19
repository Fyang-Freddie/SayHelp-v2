import json
from collections import namedtuple

from app.models import Message

# 与 app/api/chat.py 的 P1_PLACEHOLDER 逐字一致（P3 替换生成逻辑，事件契约不变）。
P1_PLACEHOLDER = "你好，我是 SayHelp 客服助手。当前为 P1 骨架阶段，完整问答将在后续阶段接入。"

SSEEvent = namedtuple("SSEEvent", ["type", "data"])


def _auth(client, username="user_a"):
    token = client.post(
        "/api/auth/login",
        data={"username": username, "password": "SayHelp123!"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def parse_sse(lines):
    """解析 SSE 的 `event: <name>\\ndata: <json>\\n\\n` 帧，返回 [(type, data)]。"""
    events = []
    event_type = None
    data = None
    for raw in lines:
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line:
            if event_type is not None:
                events.append(SSEEvent(event_type, data))
                event_type = None
                data = None
            continue
        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data = json.loads(line[len("data:"):].strip())
    if event_type is not None:
        events.append(SSEEvent(event_type, data))
    return events


def test_stream_emits_status_text_done_and_persists(client, user_a, conv_a, db_session):
    headers = _auth(client, "user_a")
    with client.stream(
        "POST", "/api/chat/stream",
        json={"conversation_id": conv_a.id, "content": "你好"},
        headers=headers,
    ) as r:
        assert r.status_code == 200
        events = parse_sse(r.iter_lines())
    assert [e.type for e in events] == ["status", "text", "done"]
    assert events[0].data == {"state": "processing"}
    assert events[1].data == {"delta": P1_PLACEHOLDER}
    assert events[2].data == {}

    msgs = (
        db_session.query(Message)
        .filter(Message.conversation_id == conv_a.id)
        .order_by(Message.id)
        .all()
    )
    assert [m.role.value for m in msgs] == ["user", "assistant"]
    assert msgs[0].content == "你好"
    assert msgs[1].content == P1_PLACEHOLDER


def test_stream_on_others_conversation_404(client, user_a, conv_b, db_session):
    headers = _auth(client, "user_a")
    with client.stream(
        "POST", "/api/chat/stream",
        json={"conversation_id": conv_b.id, "content": "x"},
        headers=headers,
    ) as r:
        assert r.status_code == 404
    assert db_session.query(Message).filter(Message.conversation_id == conv_b.id).count() == 0


def test_stream_on_nonexistent_conversation_404(client, user_a, db_session):
    headers = _auth(client, "user_a")
    with client.stream(
        "POST", "/api/chat/stream",
        json={"conversation_id": 999999, "content": "x"},
        headers=headers,
    ) as r:
        assert r.status_code == 404
    assert db_session.query(Message).count() == 0


def test_feedback_idempotent(client, user_a, msg_a, db_session):
    headers = _auth(client, "user_a")
    r1 = client.post(f"/api/messages/{msg_a.id}/feedback", json={"type": "up"}, headers=headers)
    assert r1.status_code == 200
    r2 = client.post(f"/api/messages/{msg_a.id}/feedback", json={"type": "up"}, headers=headers)
    assert r2.status_code == 200

    msg = db_session.get(Message, msg_a.id)
    assert msg.feedback["type"] == "up"
    assert "at" in msg.feedback
    # 幂等：仍是同一行上的单个 feedback 值，未新增消息行
    assert db_session.query(Message).filter(Message.id == msg_a.id).count() == 1
    assert r2.json()["feedback"] == msg.feedback

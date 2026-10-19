import json
from collections import namedtuple
from datetime import datetime

import pytest

from app.llm.client import IntentResult
from app.models import Conversation, Message
from app.workflow.graph import FIXED_TEXTS
from app.workflow.route import Branch

# P3 后闲聊走图内固定话术（与 app/workflow/graph.py 常量一致），不再是 P1 占位。
CHITCHAT_TEXT = FIXED_TEXTS[Branch.闲聊]

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


@pytest.fixture
def fake_workflow():
    """覆盖 get_workflow：闲聊确定性 fake（不调用主力模型 / 检索）。"""
    from app.api.chat import get_workflow
    from app.llm.fakes import FakeChatModel, FakeIntentModel
    from app.main import app
    from app.workflow.graph import build_workflow

    class _DummyRag:
        def retrieve(self, query, top_k=10):
            raise AssertionError("闲聊不应调用检索")

    chat = FakeChatModel()
    intent = FakeIntentModel()
    intent.next_result = IntentResult(intent="闲聊", confidence=0.9)

    def override():
        return build_workflow(chat_model=chat, intent_model=intent,
                              retriever=_DummyRag(), tools=[])

    app.dependency_overrides[get_workflow] = override
    try:
        yield {"chat": chat, "intent": intent}
    finally:
        app.dependency_overrides.pop(get_workflow, None)


def test_stream_emits_status_text_done_and_persists(client, user_a, conv_a, db_session, fake_workflow):
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
    assert events[1].data == {"delta": CHITCHAT_TEXT}
    assert events[2].data == {}

    msgs = (
        db_session.query(Message)
        .filter(Message.conversation_id == conv_a.id)
        .order_by(Message.id)
        .all()
    )
    assert [m.role.value for m in msgs] == ["user", "assistant"]
    assert msgs[0].content == "你好"
    assert msgs[1].content == CHITCHAT_TEXT


def test_stream_on_others_conversation_404(client, user_a, conv_b, db_session, fake_workflow):
    headers = _auth(client, "user_a")
    with client.stream(
        "POST", "/api/chat/stream",
        json={"conversation_id": conv_b.id, "content": "x"},
        headers=headers,
    ) as r:
        assert r.status_code == 404
    assert db_session.query(Message).filter(Message.conversation_id == conv_b.id).count() == 0


def test_stream_on_nonexistent_conversation_404(client, user_a, db_session, fake_workflow):
    headers = _auth(client, "user_a")
    with client.stream(
        "POST", "/api/chat/stream",
        json={"conversation_id": 999999, "content": "x"},
        headers=headers,
    ) as r:
        assert r.status_code == 404
    assert db_session.query(Message).count() == 0


def test_sending_message_bubbles_conversation_to_top(client, user_a, conv_a, db_session, fake_workflow):
    # 同一用户的第二个会话，用于对比排序
    conv_a2 = Conversation(user_id=user_a.id)
    db_session.add(conv_a2)
    db_session.commit()
    db_session.refresh(conv_a2)

    # 人为制造时间差：conv_a 旧、conv_a2 新，避免同一秒内创建的排序不确定
    conv_a.updated_at = datetime(2020, 1, 1)
    conv_a2.updated_at = datetime(2021, 1, 1)
    db_session.commit()

    headers = _auth(client, "user_a")
    ids = [c["id"] for c in client.get("/api/conversations", headers=headers).json()]
    assert ids == [conv_a2.id, conv_a.id]

    with client.stream(
        "POST", "/api/chat/stream",
        json={"conversation_id": conv_a.id, "content": "你好"},
        headers=headers,
    ) as r:
        assert r.status_code == 200
        list(r.iter_lines())

    ids = [c["id"] for c in client.get("/api/conversations", headers=headers).json()]
    assert ids == [conv_a.id, conv_a2.id]


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

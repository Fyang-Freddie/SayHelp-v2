from app.models import Conversation, Message, UserRole
from app.schemas import MessageOut


def _auth(client, username="agent"):
    token = client.post("/api/auth/login",
                        data={"username": username, "password": "SayHelp123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_agent_claims_and_replies_with_sender_name(client, user_factory, db_session):
    customer = user_factory(username="cust_x", role=UserRole.customer, customer_id="C0001")
    agent = user_factory(username="agent_x", role=UserRole.agent, display_name="坐席 王小明")
    conv = Conversation(user_id=customer.id, status="agent_waiting")
    db_session.add(conv); db_session.commit(); db_session.refresh(conv)

    h = _auth(client, "agent_x")
    r = client.get("/api/agent/conversations", params={"status": "agent_waiting"}, headers=h)
    assert r.status_code == 200
    assert any(c["id"] == conv.id for c in r.json())

    r = client.post(f"/api/agent/conversations/{conv.id}/claim", headers=h)
    assert r.status_code == 200
    db_session.refresh(conv)
    assert conv.status == "agent_connected"

    r = client.post(f"/api/agent/conversations/{conv.id}/messages",
                    json={"content": "您好，我是坐席"}, headers=h)
    assert r.status_code == 200
    body = MessageOut.model_validate(r.json())
    assert body.sender_name == "坐席 王小明"
    msg = db_session.query(Message).filter(Message.conversation_id == conv.id).one()
    assert msg.sender_id == agent.id
    assert msg.role.value == "assistant"


def test_customer_cannot_access_agent_endpoints(client, user_factory, db_session):
    customer = user_factory(username="cust_y", role=UserRole.customer, customer_id="C0002")
    conv = Conversation(user_id=customer.id)
    db_session.add(conv); db_session.commit(); db_session.refresh(conv)
    h = _auth(client, "cust_y")
    assert client.post(f"/api/agent/conversations/{conv.id}/claim", headers=h).status_code == 403


def test_agent_list_filters_by_status(client, user_factory, db_session):
    """?status= 参数须真正过滤，未被声明的查询参数不能被 FastAPI 静默忽略。"""
    customer = user_factory(username="cust_w", role=UserRole.customer, customer_id="C0004")
    agent = user_factory(username="agent_w", role=UserRole.agent)
    waiting = Conversation(user_id=customer.id, status="agent_waiting")
    connected = Conversation(user_id=customer.id, status="agent_connected")
    db_session.add_all([waiting, connected]); db_session.commit()
    db_session.refresh(waiting); db_session.refresh(connected)

    h = _auth(client, "agent_w")
    r = client.get("/api/agent/conversations", params={"status": "agent_connected"}, headers=h)
    ids = [c["id"] for c in r.json()]
    assert connected.id in ids
    assert waiting.id not in ids


def test_agent_reply_falls_back_when_display_name_empty(client, user_factory, db_session):
    """坐席 display_name 为空时 sender_name 仍须非空，绝不把坐席回复冒充为 AI。"""
    customer = user_factory(username="cust_z", role=UserRole.customer, customer_id="C0005")
    agent = user_factory(username="agent_z", role=UserRole.agent)   # display_name=None
    conv = Conversation(user_id=customer.id, status="agent_waiting")
    db_session.add(conv); db_session.commit(); db_session.refresh(conv)

    h = _auth(client, "agent_z")
    r = client.post(f"/api/agent/conversations/{conv.id}/messages",
                    json={"content": "您好，我是坐席"}, headers=h)
    assert r.status_code == 200
    assert r.json()["sender_name"] is not None
    assert r.json()["sender_name"] != ""

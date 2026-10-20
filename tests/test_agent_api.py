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

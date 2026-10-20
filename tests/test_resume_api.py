import json

from app.models import Ticket
from app.tools.interrupt import sign_interrupt


def _auth(client, username="user_a"):
    token = client.post("/api/auth/login",
                        data={"username": username, "password": "SayHelp123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_transfer_sets_agent_waiting(client, user_a, conv_a, db_session):
    token, _ = sign_interrupt(conv_a.id, "transfer_human")
    r = client.post("/api/chat/resume", json={
        "conversation_id": conv_a.id, "interrupt_id": token,
        "action": "transfer", "payload": {}}, headers=_auth(client, "user_a"))
    assert r.status_code == 200
    db_session.refresh(conv_a)
    assert conv_a.status == "agent_waiting"


def test_confirm_ticket_idempotent(client, user_a, conv_a, db_session):
    h = _auth(client, "user_a")
    token, _ = sign_interrupt(conv_a.id, "ticket_confirm")
    body = {"conversation_id": conv_a.id, "interrupt_id": token,
            "action": "confirm_ticket", "payload": {"description": "物流慢", "type": "投诉"}}
    r1 = client.post("/api/chat/resume", json=body, headers=h)
    r2 = client.post("/api/chat/resume", json=body, headers=h)   # 双击重放
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["ticket_no"] == r2.json()["ticket_no"]
    assert db_session.query(Ticket).count() == 1                 # 幂等只落一张


def test_confirm_ticket_audits_tool_execution(client, user_a, conv_a, db_session):
    from app.models.flywheel import ToolAuditLog

    token, _ = sign_interrupt(conv_a.id, "ticket_confirm")
    r = client.post("/api/chat/resume", json={
        "conversation_id": conv_a.id, "interrupt_id": token,
        "action": "confirm_ticket", "payload": {"description": "物流慢", "type": "投诉"}},
        headers=_auth(client, "user_a"))
    assert r.status_code == 200
    logs = (db_session.query(ToolAuditLog)
            .filter(ToolAuditLog.tool_name == "create_ticket").all())
    assert len(logs) == 1                       # 建工单走统一执行引擎 → 落审计
    assert logs[0].status.value == "成功"


def test_resume_rejects_cross_session(client, user_a, user_b, conv_a, conv_b):
    token, _ = sign_interrupt(conv_a.id, "transfer_human")
    r = client.post("/api/chat/resume", json={
        "conversation_id": conv_b.id, "interrupt_id": token,
        "action": "transfer", "payload": {}}, headers=_auth(client, "user_b"))
    assert r.status_code == 400                                  # 防跨会话 resume


def test_select_order_returns_refund_preview_no_ticket(client, user_a, conv_a, db_session):
    token, _ = sign_interrupt(conv_a.id, "order_select")
    r = client.post("/api/chat/resume", json={
        "conversation_id": conv_a.id, "interrupt_id": token,
        "action": "select_order", "payload": {"order_no": "O1", "item_id": "ITEM1"}},
        headers=_auth(client, "user_a"))
    assert r.status_code == 200
    data = r.json()
    assert data["card"]["type"] == "refund_preview"
    assert "退款未真实提交" in data["card"]["payload"]["notice"]   # 诚实：不冒报提交
    assert db_session.query(Ticket).count() == 0

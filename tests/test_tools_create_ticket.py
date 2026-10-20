import json

from app.models import Ticket
from app.tools.builtin import create_ticket_handler
from app.tools.context import ExecutionContext

CTX = ExecutionContext(caller_user_id=1, caller_role="customer",
                       customer_id="C0001", conversation_id=7, confirmed=True)


def test_create_ticket_writes_one_ticket(db_session):
    out = json.loads(create_ticket_handler(
        {"description": "物流丢失", "type": "投诉", "idempotency_key": "K1"}, CTX, db_session))
    ticket = db_session.query(Ticket).one()
    assert ticket.ticket_no == out["ticket_no"]
    assert ticket.conversation_id == 7
    assert ticket.status == "open"
    assert ticket.idempotency_key == "K1"


def test_create_ticket_is_idempotent(db_session):
    a = create_ticket_handler({"description": "x", "type": "投诉", "idempotency_key": "K1"}, CTX, db_session)
    b = create_ticket_handler({"description": "x", "type": "投诉", "idempotency_key": "K1"}, CTX, db_session)
    assert json.loads(a)["ticket_no"] == json.loads(b)["ticket_no"]
    assert db_session.query(Ticket).count() == 1        # 只落一张

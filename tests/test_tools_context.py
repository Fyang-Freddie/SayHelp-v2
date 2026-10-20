from app.models import UserRole
from app.models.conversation import Conversation
from app.tools.context import ExecutionContext, build_execution_context


def test_build_context_takes_owner_customer_id_not_caller(user_factory, db_session):
    owner = user_factory(username="cust_1", role=UserRole.customer, customer_id="C0001")
    agent = user_factory(username="agent_1", role=UserRole.agent, customer_id=None)
    conv = Conversation(user_id=owner.id)
    db_session.add(conv); db_session.commit(); db_session.refresh(conv)

    ctx = build_execution_context(caller=agent, owner=owner, conversation=conv, confirmed=True)
    assert ctx.caller_user_id == agent.id
    assert ctx.caller_role == "agent"
    assert ctx.customer_id == "C0001"          # 取 owner 的客户ID，非 caller
    assert ctx.conversation_id == conv.id
    assert ctx.confirmed is True


def test_build_context_default_not_confirmed(user_factory, db_session):
    owner = user_factory(username="cust_2", role=UserRole.customer, customer_id="C0002")
    conv = Conversation(user_id=owner.id)
    db_session.add(conv); db_session.commit(); db_session.refresh(conv)
    ctx = build_execution_context(caller=owner, owner=owner, conversation=conv)
    assert ctx.confirmed is False

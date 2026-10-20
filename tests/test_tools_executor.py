from datetime import datetime

from app.models import Order
from app.models.flywheel import ToolAuditLog, ToolStatus
from app.tools.context import ExecutionContext
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry, ToolSpec


def _ctx(customer_id="C0001", confirmed=False):
    return ExecutionContext(caller_user_id=1, caller_role="customer",
                            customer_id=customer_id, conversation_id=1, confirmed=confirmed)


def _registry():
    reg = ToolRegistry()
    reg.register(ToolSpec(name="query_product", description="查商品", input_schema={"type": "object"},
                          source="builtin",
                          handler=lambda args, ctx, db: f"商品:{args.get('name')}"))
    reg.register(ToolSpec(name="query_order", description="查订单", input_schema={"type": "object"},
                          source="builtin", requires_customer=True,
                          handler=lambda args, ctx, db: f"订单:{ctx.customer_id}:{args.get('order_no')}"))
    reg.register(ToolSpec(name="create_ticket", description="建工单", input_schema={"type": "object"},
                          source="builtin", is_write=True, visible_to_agent=False,
                          handler=lambda args, ctx, db: "工单已建"))
    return reg


def test_execute_success_returns_observation_and_audits(db_session):
    ex = ToolExecutor(_registry(), db_session)
    out = ex.execute("query_product", {"name": "手机"}, _ctx())
    assert out == "商品:手机"
    log = db_session.query(ToolAuditLog).one()
    assert log.tool_name == "query_product"
    assert log.status == ToolStatus.success
    assert log.tool_source.value == "builtin"


def test_execute_requires_customer_denies_when_no_customer(db_session):
    ex = ToolExecutor(_registry(), db_session)
    out = ex.execute("query_order", {"order_no": "O1"}, _ctx(customer_id=None))
    assert "无权" in out
    assert db_session.query(ToolAuditLog).one().status == ToolStatus.permission_denied


def test_execute_write_requires_confirmed(db_session):
    ex = ToolExecutor(_registry(), db_session)
    out = ex.execute("create_ticket", {"description": "x"}, _ctx(confirmed=False))
    assert "确认" in out
    assert db_session.query(ToolAuditLog).one().status == ToolStatus.validation_blocked


def test_execute_write_allowed_when_confirmed(db_session):
    ex = ToolExecutor(_registry(), db_session)
    out = ex.execute("create_ticket", {"description": "x"}, _ctx(confirmed=True))
    assert out == "工单已建"
    assert db_session.query(ToolAuditLog).one().status == ToolStatus.success


def test_execute_handler_exception_returns_observation_and_audits_failure(db_session):
    reg = ToolRegistry()
    def boom(args, ctx, db): raise ValueError("boom")
    reg.register(ToolSpec(name="bad", description="b", input_schema={"type": "object"},
                          source="builtin", handler=boom))
    ex = ToolExecutor(reg, db_session)
    out = ex.execute("bad", {}, _ctx())
    assert "失败" in out
    assert db_session.query(ToolAuditLog).one().status == ToolStatus.failure


def test_execute_mcp_ownership_field_denies_foreign_order(db_session):
    # 归属预检：order_no 属于 C0002，而 ctx.customer_id 是 C0001 → 拒绝（Review Focus #1）
    db_session.add(Order(customer_id="C0002", order_no="O2", item_id="ITEM2", product_name="x",
                         quantity=1, paid_amount=1, order_status="已签收", after_sale_status="无售后",
                         order_time=datetime(2026, 1, 1)))
    db_session.commit()
    reg = ToolRegistry()
    reg.register(ToolSpec(name="query_logistics", description="查物流", input_schema={"type": "object"},
                          source="mcp", mcp_server="logistics", requires_customer=True,
                          ownership_field="order_no"))
    ex = ToolExecutor(reg, db_session)
    out = ex.execute("query_logistics", {"order_no": "O2"}, _ctx(customer_id="C0001"))
    assert "无权" in out
    assert db_session.query(ToolAuditLog).one().status == ToolStatus.permission_denied


def test_agent_tools_wraps_run_through_executor(db_session):
    ex = ToolExecutor(_registry(), db_session)
    tools = {t.name: t for t in ex.agent_tools(_ctx())}
    assert set(tools) == {"query_product", "query_order"}   # create_ticket 不可见
    assert tools["query_order"].run({"order_no": "O1"}) == "订单:C0001:O1"
    assert db_session.query(ToolAuditLog).count() == 1      # run 走执行器：audit 落库

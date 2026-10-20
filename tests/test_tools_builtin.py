import json
from datetime import datetime

from app.models import Order, Product
from app.rag.retrieval import RetrievalResult, ScoredChunk
from app.tools.builtin import (query_faq_handler, query_order_handler,
                               query_product_handler, register_builtin_tools)
from app.tools.context import ExecutionContext
from app.tools.registry import ToolRegistry

CTX = ExecutionContext(caller_user_id=1, caller_role="customer",
                       customer_id="C0001", conversation_id=1)


def _seed_order(db, customer_id="C0001", order_no="O1", item_id="ITEM1", name="手机"):
    db.add(Order(customer_id=customer_id, order_no=order_no, item_id=item_id,
                 product_name=name, quantity=1, paid_amount=1999, order_status="已签收",
                 after_sale_status="无售后", order_time=datetime(2026, 10, 1)))
    db.commit()


def test_query_order_returns_only_own_orders(db_session):
    _seed_order(db_session, customer_id="C0001", order_no="O1")
    _seed_order(db_session, customer_id="C0002", order_no="O2", item_id="ITEM2")
    out = json.loads(query_order_handler({}, CTX, db_session))
    assert [o["order_no"] for o in out["orders"]] == ["O1"]      # 越权订单被过滤


def test_query_order_filters_by_order_no(db_session):
    _seed_order(db_session, order_no="O1")
    _seed_order(db_session, order_no="O9", item_id="ITEM9")
    out = json.loads(query_order_handler({"order_no": "O1"}, CTX, db_session))
    assert [o["order_no"] for o in out["orders"]] == ["O1"]


def test_query_product_by_name_and_model(db_session):
    db_session.add(Product(product_name="手机A", model="M1", order_spec="128G",
                           product_type="数码", seven_day_return="支持", warranty="12个月"))
    db_session.commit()
    out = json.loads(query_product_handler({"product_name": "手机A"}, CTX, db_session))
    assert out["products"][0]["model"] == "M1"
    out2 = json.loads(query_product_handler({"model": "M1"}, CTX, db_session))
    assert out2["products"][0]["warranty"] == "12个月"


class _Rag:
    def retrieve(self, query, top_k=10):
        return RetrievalResult(
            chunks=[ScoredChunk(chunk_id=1, score=0.9, category="政策",
                                section_path="政策 > R01", content_type="policy",
                                snippet="七天无理由退货")],
            evidence_confidence=0.9, passed=True)


def test_query_faq_returns_numbered_evidence():
    out = json.loads(query_faq_handler({"query": "退货政策"}, CTX, retriever=_Rag()))
    assert out["passed"] is True
    assert out["evidence"][0]["n"] == 1
    assert "七天无理由退货" in out["evidence"][0]["snippet"]


def test_query_faq_gate_fail_returns_honest():
    class _RagFail:
        def retrieve(self, query, top_k=10):
            return RetrievalResult(chunks=[], evidence_confidence=0.1, passed=False)
    out = json.loads(query_faq_handler({"query": "x"}, CTX, retriever=_RagFail()))
    assert out["passed"] is False and out["evidence"] == []


def test_register_builtin_tools_registers_read_tools():
    reg = ToolRegistry()
    register_builtin_tools(reg, retriever=_Rag())
    names = {s.name for s in reg.list_for_agent()}
    assert names == {"query_order", "query_product", "query_faq"}
    assert reg.resolve("query_order").requires_customer is True

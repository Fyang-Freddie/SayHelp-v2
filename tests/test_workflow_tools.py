from app.llm.client import IntentResult
from app.llm.fakes import FakeChatModel, FakeIntentModel
from app.rag.retrieval import RetrievalResult, ScoredChunk
from app.tools.context import ExecutionContext
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry, ToolSpec
from app.workflow.graph import build_workflow


class _Rag:
    def retrieve(self, query, top_k=10):
        return RetrievalResult(
            chunks=[ScoredChunk(chunk_id=1, score=0.9, category="政策", section_path="R01",
                                content_type="policy", snippet="七天无理由")],
            evidence_confidence=0.9, passed=True)


def _graph(intent, chat=None, retriever=None):
    intent_model = FakeIntentModel(); intent_model.next_result = IntentResult(intent=intent, confidence=0.9)
    chat_model = chat or FakeChatModel()
    return build_workflow(chat_model=chat_model, intent_model=intent_model,
                          retriever=retriever or _Rag())


def _ctx():
    return ExecutionContext(caller_user_id=1, caller_role="customer",
                            customer_id="C0001", conversation_id=1)


def test_agent_invokes_tool_via_executor(db_session):
    chat = FakeChatModel()
    chat.next_actions = [("tool_call", {"name": "query_product", "args": {}}),
                         ("final", "已查到商品:手机")]
    graph = _graph("物流", chat=chat)
    reg = ToolRegistry()
    reg.register(ToolSpec(name="query_product", description="查商品", input_schema={"type": "object"},
                          source="builtin", handler=lambda a, c, db: "商品:手机"))
    ex = ToolExecutor(reg, db_session)
    out = graph.invoke({"messages": [{"role": "user", "content": "查商品"}],
                        "ctx": _ctx(), "agent_tools": ex.agent_tools(_ctx())})
    assert "手机" in out["answer"]


def test_refund_emits_order_select_card():
    graph = _graph("退款退货")
    out = graph.invoke({"messages": [{"role": "user", "content": "我要退货"}],
                        "ctx": _ctx(), "agent_tools": []})
    assert out.get("card", {}).get("type") == "order_select"
    assert out["card"]["interrupt_id"]


def test_complaint_emits_handoff_card():
    graph = _graph("投诉")
    out = graph.invoke({"messages": [{"role": "user", "content": "我要投诉"}],
                        "ctx": _ctx(), "agent_tools": []})
    assert out["card"]["type"] == "transfer_human"
    assert out["card"]["interrupt_id"]
    assert "已记录" not in out["answer"]
    assert "已受理" not in out["answer"]

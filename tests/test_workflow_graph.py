# tests/test_workflow_graph.py
from app.llm.fakes import FakeChatModel, FakeIntentModel
from app.llm.client import IntentResult
from app.tools.context import ExecutionContext
from app.workflow.graph import build_workflow


def _ctx():
    return ExecutionContext(caller_user_id=1, caller_role="customer",
                            customer_id="C0001", conversation_id=1)


class _Rag:
    def retrieve(self, query, top_k=10):
        from app.rag.retrieval import RetrievalResult, ScoredChunk
        return RetrievalResult(
            chunks=[ScoredChunk(chunk_id=1, score=0.9, category="售后政策",
                                section_path="售后政策 > A06【保修期限】",
                                content_type="manual", snippet="手机 12 个月")],
            evidence_confidence=0.9, passed=True)


def test_graph_chitchat_returns_fixed_text_without_model():
    intent = FakeIntentModel(); intent.next_result = IntentResult(intent="闲聊", confidence=0.9)
    chat = FakeChatModel(); chat.next_text = "不该被调用"
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_Rag())
    out = graph.invoke({"messages": [{"role": "user", "content": "你好"}],
                        "ctx": _ctx(), "agent_tools": []})
    assert "SayHelp" in out["answer"]
    assert chat.called is False  # 闲聊不调用主力模型


def test_graph_product_qa_end_to_end():
    intent = FakeIntentModel(); intent.next_result = IntentResult(intent="商品咨询", confidence=0.9)
    chat = FakeChatModel(); chat.next_text = "该商品保修 12 个月"
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_Rag())
    out = graph.invoke({"messages": [{"role": "user", "content": "手机保修多久"}],
                        "ctx": _ctx(), "agent_tools": []})
    assert out["answer"] == "该商品保修 12 个月"
    assert [c.index for c in out["citations"]] == [1]


def test_graph_complaint_emits_handoff_card():
    intent = FakeIntentModel(); intent.next_result = IntentResult(intent="投诉", confidence=0.9)
    chat = FakeChatModel(); chat.next_text = "不该被调用"
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_Rag())
    out = graph.invoke({"messages": [{"role": "user", "content": "我要投诉你们"}],
                        "ctx": _ctx(), "agent_tools": []})
    ans = out["answer"]
    assert out.get("card", {}).get("type") == "transfer_human"
    assert "转人工" in ans or "转接" in ans       # 诚实指向真人，不冒报已受理
    assert "已记录" not in ans
    assert "已受理" not in ans


class _RecordingChat:
    """记录 run_agent 传入的 messages，供断言证据是否带 [n] 编号前缀。"""

    def __init__(self):
        self.messages = []
        self.called = False

    def complete(self, messages):
        self.called = True
        return ""

    def complete_json(self, messages, json_schema):
        self.called = True
        self.messages = messages
        return {"action": "final", "text": "根据资料回答"}


class _Rag2:
    def retrieve(self, query, top_k=10):
        from app.rag.retrieval import RetrievalResult, ScoredChunk
        return RetrievalResult(
            chunks=[
                ScoredChunk(chunk_id=1, score=0.9, category="售后政策",
                            section_path="售后政策 > A06【保修期限】",
                            content_type="manual", snippet="手机 12 个月"),
                ScoredChunk(chunk_id=2, score=0.8, category="商品规格手册",
                            section_path="商品规格手册 > B02【电池】",
                            content_type="manual", snippet="电池 5000mAh"),
            ],
            evidence_confidence=0.9, passed=True)


def test_graph_product_qa_injects_numbered_evidence():
    """agent 拿到的证据须按 [n] 1-based 编号，与 build_citations 对齐。"""
    intent = FakeIntentModel(); intent.next_result = IntentResult(intent="商品咨询", confidence=0.9)
    chat = _RecordingChat()
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_Rag2())
    out = graph.invoke({"messages": [{"role": "user", "content": "手机保修多久"}],
                        "ctx": _ctx(), "agent_tools": []})
    assert out["answer"] == "根据资料回答"

    evidence = "\n".join(m["content"] for m in chat.messages if m["role"] == "system")
    assert "[1] 手机 12 个月" in evidence
    assert "[2] 电池 5000mAh" in evidence


def test_graph_logistics_runs_agent():
    intent = FakeIntentModel(); intent.next_result = IntentResult(intent="物流", confidence=0.9)
    chat = FakeChatModel()
    chat.next_actions = [("final", "物流信息如下")]
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_Rag())
    out = graph.invoke({"messages": [{"role": "user", "content": "我的快递到哪了"}],
                        "ctx": _ctx(), "agent_tools": []})
    assert out["answer"] == "物流信息如下"        # 物流分支走 agent 而非占位话术


def test_graph_product_qa_refuses_when_gate_fails():
    from app.rag.retrieval import RetrievalResult

    class _RagFail:
        def retrieve(self, query, top_k=10):
            return RetrievalResult(chunks=[], evidence_confidence=0.1, passed=False)

    intent = FakeIntentModel(); intent.next_result = IntentResult(intent="商品咨询", confidence=0.9)
    chat = FakeChatModel(); chat.next_text = "不该被调用"
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_RagFail())
    out = graph.invoke({"messages": [{"role": "user", "content": "手机保修多久"}],
                        "ctx": _ctx(), "agent_tools": []})
    assert "暂" in out["answer"] or "无法" in out["answer"]  # 闸不过诚实拒答
    assert out["citations"] == []  # 未过闸不得编造引用

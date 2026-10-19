# tests/test_workflow_graph.py
from app.llm.fakes import FakeChatModel, FakeIntentModel
from app.llm.client import IntentResult
from app.workflow.graph import build_workflow


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
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_Rag(), tools=[])
    out = graph.invoke({"messages": [{"role": "user", "content": "你好"}]})
    assert "SayHelp" in out["answer"]
    assert chat.called is False  # 闲聊不调用主力模型


def test_graph_product_qa_end_to_end():
    intent = FakeIntentModel(); intent.next_result = IntentResult(intent="商品咨询", confidence=0.9)
    chat = FakeChatModel(); chat.next_text = "该商品保修 12 个月"
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_Rag(), tools=[])
    out = graph.invoke({"messages": [{"role": "user", "content": "手机保修多久"}]})
    assert out["answer"] == "该商品保修 12 个月"
    assert [c.index for c in out["citations"]] == [1]


def test_graph_logistics_returns_honest_stub():
    intent = FakeIntentModel(); intent.next_result = IntentResult(intent="物流", confidence=0.9)
    chat = FakeChatModel(); chat.next_text = "不该被调用"
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_Rag(), tools=[])
    out = graph.invoke({"messages": [{"role": "user", "content": "我的快递到哪了"}]})
    assert "后续" in out["answer"] or "暂" in out["answer"]  # 诚实降级，不伪造物流结果


def test_graph_product_qa_refuses_when_gate_fails():
    from app.rag.retrieval import RetrievalResult

    class _RagFail:
        def retrieve(self, query, top_k=10):
            return RetrievalResult(chunks=[], evidence_confidence=0.1, passed=False)

    intent = FakeIntentModel(); intent.next_result = IntentResult(intent="商品咨询", confidence=0.9)
    chat = FakeChatModel(); chat.next_text = "不该被调用"
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_RagFail(), tools=[])
    out = graph.invoke({"messages": [{"role": "user", "content": "手机保修多久"}]})
    assert "暂" in out["answer"] or "无法" in out["answer"]  # 闸不过诚实拒答
    assert out["citations"] == []  # 未过闸不得编造引用

"""Task 7：SSE 主链路接线 + 商品咨询端到端的 API 测试。

复用 conftest 的 client / user_a / conv_a / db_session，通过 ``dependency_overrides``
注入确定性 fake workflow（覆盖 ``get_workflow``），断言事件契约：
``status → text → [reference] → done``，以及 assistant 消息连同 citations 落库。
"""
import json
from collections import namedtuple

import pytest

from app.llm.client import IntentResult
from app.models import Message
from app.rag.retrieval import RetrievalResult, ScoredChunk

SSEEvent = namedtuple("SSEEvent", ["type", "data"])


def _auth(client, username="user_a"):
    token = client.post(
        "/api/auth/login",
        data={"username": username, "password": "SayHelp123!"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def parse_sse(lines):
    events = []
    event_type = None
    data = None
    for raw in lines:
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line:
            if event_type is not None:
                events.append(SSEEvent(event_type, data))
                event_type = None
                data = None
            continue
        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data = json.loads(line[len("data:"):].strip())
    if event_type is not None:
        events.append(SSEEvent(event_type, data))
    return events


class _Rag:
    def retrieve(self, query, top_k=10):
        return RetrievalResult(
            chunks=[ScoredChunk(chunk_id=1, score=0.9, category="售后政策",
                                section_path="售后政策 > A06【保修期限】",
                                content_type="manual", snippet="手机 12 个月")],
            evidence_confidence=0.9, passed=True)


class _RagFail:
    def retrieve(self, query, top_k=10):
        return RetrievalResult(chunks=[], evidence_confidence=0.1, passed=False)


@pytest.fixture
def fake_workflow():
    """覆盖 get_workflow：确定性 fakes，默认闲聊 + 通过闸的 RAG。

    返回 {"chat", "intent", "rag"}；测试可改 intent.next_result / chat.next_text，
    或把 rag 换成自定义 retriever（实现 retrieve(query, top_k) 即可）。
    同时覆盖 get_tool_registry 返回空注册中心，避免 chat_stream 构建真实 MCP 注册中心。
    """
    from app.api.chat import get_workflow, get_tool_registry
    from app.llm.fakes import FakeChatModel, FakeIntentModel
    from app.main import app
    from app.tools.registry import ToolRegistry
    from app.workflow.graph import build_workflow

    chat = FakeChatModel()
    intent = FakeIntentModel()
    intent.next_result = IntentResult(intent="闲聊", confidence=0.9)
    ctx = {"chat": chat, "intent": intent, "rag": _Rag()}

    def override():
        return build_workflow(chat_model=ctx["chat"], intent_model=ctx["intent"],
                              retriever=ctx["rag"])

    def override_registry():
        return ToolRegistry()   # 空注册中心：测试不触 MCP 网络

    app.dependency_overrides[get_workflow] = override
    app.dependency_overrides[get_tool_registry] = override_registry
    try:
        yield ctx
    finally:
        app.dependency_overrides.pop(get_workflow, None)
        app.dependency_overrides.pop(get_tool_registry, None)


def test_chat_stream_chitchat_returns_fixed_text(client, user_a, conv_a, fake_workflow):
    headers = _auth(client, "user_a")
    with client.stream(
        "POST", "/api/chat/stream",
        json={"conversation_id": conv_a.id, "content": "你好"},
        headers=headers,
    ) as r:
        assert r.status_code == 200
        events = parse_sse(r.iter_lines())
    assert [e.type for e in events] == ["status", "text", "done"]
    assert "SayHelp" in events[1].data["delta"]
    assert fake_workflow["chat"].called is False  # 闲聊不调用主力模型


def test_chat_stream_product_qa_returns_reference(client, user_a, conv_a, db_session, fake_workflow):
    fake_workflow["intent"].next_result = IntentResult(intent="商品咨询", confidence=0.9)
    fake_workflow["chat"].next_text = "该商品保修 12 个月"
    headers = _auth(client, "user_a")
    with client.stream(
        "POST", "/api/chat/stream",
        json={"conversation_id": conv_a.id, "content": "手机保修多久"},
        headers=headers,
    ) as r:
        assert r.status_code == 200
        events = parse_sse(r.iter_lines())
    assert [e.type for e in events] == ["status", "text", "reference", "done"]
    assert events[1].data == {"delta": "该商品保修 12 个月"}
    assert events[2].data["citations"][0]["section_path"] == "售后政策 > A06【保修期限】"
    assert events[2].data["citations"][0]["chunk_id"] == 1

    msgs = (
        db_session.query(Message)
        .filter(Message.conversation_id == conv_a.id)
        .order_by(Message.id)
        .all()
    )
    assert [m.role.value for m in msgs] == ["user", "assistant"]
    assert msgs[1].content == "该商品保修 12 个月"
    assert msgs[1].citations["citations"][0]["chunk_id"] == 1


def test_chat_stream_product_qa_gate_fail_refuses(client, user_a, conv_a, db_session, fake_workflow):
    fake_workflow["intent"].next_result = IntentResult(intent="商品咨询", confidence=0.9)
    fake_workflow["rag"] = _RagFail()
    headers = _auth(client, "user_a")
    with client.stream(
        "POST", "/api/chat/stream",
        json={"conversation_id": conv_a.id, "content": "手机保修多久"},
        headers=headers,
    ) as r:
        assert r.status_code == 200
        events = parse_sse(r.iter_lines())
    assert [e.type for e in events] == ["status", "text", "done"]  # 闸不过无 reference
    text = events[1].data["delta"]
    assert "暂" in text or "无法" in text  # 诚实拒答

    msgs = (
        db_session.query(Message)
        .filter(Message.conversation_id == conv_a.id)
        .order_by(Message.id)
        .all()
    )
    assert msgs[1].citations is None  # 不得伪造引用


def test_chat_stream_passes_prior_history_to_workflow(client, user_a, conv_a, db_session):
    """多轮历史接入：第二次 invoke 应收到首轮 user 内容，且当前 user 消息在末尾。"""
    from app.api.chat import get_workflow, get_tool_registry
    from app.main import app
    from app.tools.registry import ToolRegistry

    calls = []

    class _SpyWorkflow:
        def invoke(self, state):
            calls.append(state)
            return {"answer": "已作答", "citations": []}

    app.dependency_overrides[get_workflow] = lambda: _SpyWorkflow()
    app.dependency_overrides[get_tool_registry] = lambda: ToolRegistry()
    headers = _auth(client, "user_a")
    try:
        for content in ("手机保修多久", "那电池呢"):
            with client.stream(
                "POST", "/api/chat/stream",
                json={"conversation_id": conv_a.id, "content": content},
                headers=headers,
            ) as r:
                assert r.status_code == 200
                list(r.iter_lines())
    finally:
        app.dependency_overrides.pop(get_workflow, None)
        app.dependency_overrides.pop(get_tool_registry, None)

    assert len(calls) == 2
    second = calls[1]["messages"]
    assert {"role": "user", "content": "手机保修多久"} in second
    assert second[-1] == {"role": "user", "content": "那电池呢"}


def test_get_workflow_is_shared_lazy_singleton():
    """工厂单例：两次直接调用同一对象，且仅调用 get_workflow() 不 import 重库。"""
    import sys

    from app.api.chat import get_workflow

    before = set(sys.modules)
    w1 = get_workflow()
    w2 = get_workflow()
    after = set(sys.modules)

    assert w1 is w2
    assert "langchain_openai" not in (after - before)
    assert "pymilvus" not in (after - before)


def test_build_real_workflow_retriever_is_fully_lazy():
    """构建真实工作流本身不 import pymilvus/FlagEmbedding（检索延后到首次 retrieve()）。"""
    import sys

    from app.api.chat import _build_real_workflow

    before = set(sys.modules)
    graph = _build_real_workflow()
    after = set(sys.modules)

    assert graph is not None
    assert "pymilvus" not in (after - before)
    assert "FlagEmbedding" not in (after - before)




def test_chat_stream_logistics_runs_agent(client, user_a, conv_a, fake_workflow):
    fake_workflow["intent"].next_result = IntentResult(intent="物流", confidence=0.9)
    fake_workflow["chat"].next_actions = [("final", "物流信息如下")]
    headers = _auth(client, "user_a")
    with client.stream(
        "POST", "/api/chat/stream",
        json={"conversation_id": conv_a.id, "content": "我的快递到哪了"},
        headers=headers,
    ) as r:
        assert r.status_code == 200
        events = parse_sse(r.iter_lines())
    assert [e.type for e in events] == ["status", "text", "done"]
    assert events[1].data == {"delta": "物流信息如下"}

"""P3 聊天工作流组装（GRAPH 节点）。

把 Task 2–5 与 P2 检索编排组装成一条 LangGraph 图：

    START → resolve → classify → 条件边按 Branch 分流
      ├─ 商品咨询 → product_qa（RAG → 闸 → agent）
      ├─ 闲聊/投诉/其他 → fixed_text（固定话术）
      └─ 退款退货/售后/物流订单 → honest_stub（诚实占位，绝不伪造结果）
    → final → END

闸逻辑已内建在 ``Retriever.retrieve()`` 的 ``passed`` 字段里，本图只读该字段，
不重复实现闸。
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph

from app.config import settings
from app.llm.client import IntentResult
from app.rag.citations import Citation, build_citations
from app.rag.retrieval import RetrievalResult
from app.workflow.agent import run_agent
from app.workflow.intent import classify_intent
from app.workflow.resolve import resolve_reference
from app.workflow.route import Branch, route


class WorkflowState(TypedDict):
    """图状态。``messages`` 用 add_messages 累加；其余键普通覆盖。"""

    messages: Annotated[list, add_messages]
    resolved_text: str
    intent_result: IntentResult
    branch: Branch
    evidence: RetrievalResult
    passed: bool
    answer: str
    citations: list[Citation]


# 闸不过时的诚实拒答文本（含「暂」/「无法」）。
REFUSE_TEXT = "抱歉，暂无法确认该信息，请稍后重试或转人工。"

# 固定话术：闲聊 / 投诉 / 其他。闲聊话术必须含「SayHelp」。
FIXED_TEXTS = {
    Branch.闲聊: "您好，我是 SayHelp 客服助手，很高兴为您服务。请问有什么可以帮您？",
    Branch.投诉: "非常抱歉给您带来不便，我们已记录您的投诉，会尽快核实并处理，感谢您的耐心。",
    Branch.其他: "抱歉，我还不能完全理解您的问题，请您换个方式描述一下，或转人工协助。",
}

# 诚实占位：退款退货 / 售后 / 物流订单。绝不伪造订单、物流、退款结果。
HONEST_STUBS = {
    Branch.退款退货: "退款退货处理能力将在后续阶段接入，暂无法为您办理，请稍后再试。",
    Branch.售后: "售后服务能力将在后续阶段接入，暂无法为您处理，请稍后再试。",
    Branch.物流订单: "物流查询能力将在后续阶段接入，暂无法查询，请稍后再试。",
}


def _msg_to_dict(m) -> dict:
    """把 langchain 消息对象（或已是 dict 的消息）还原成 Task 2/5 要的普通 dict。"""
    if isinstance(m, dict):
        return m
    role = getattr(m, "type", None) or "user"  # "human"/"ai"/"system"
    role_map = {"human": "user", "ai": "assistant", "system": "system"}
    return {"role": role_map.get(role, "user"), "content": getattr(m, "content", "") or ""}


def build_workflow(*, chat_model, intent_model, retriever, tools, settings=settings) -> CompiledStateGraph:
    """组装聊天工作流，返回可 ``.invoke()`` 的编译图。"""

    def _resolve(state: WorkflowState) -> dict:
        msgs = state["messages"] or []
        last = msgs[-1] if msgs else None
        current_text = _msg_to_dict(last)["content"] if last is not None else ""
        history = [_msg_to_dict(x) for x in msgs[:-1]]
        resolved = resolve_reference(chat_model, history, current_text)
        return {"resolved_text": resolved}

    def _classify(state: WorkflowState) -> dict:
        result = classify_intent(
            intent_model, state["resolved_text"], threshold=settings.intent_confidence_threshold
        )
        return {"intent_result": result, "branch": route(result.intent)}

    def _route_by_branch(state: WorkflowState) -> Branch:
        return state["branch"]

    def _product_qa(state: WorkflowState) -> dict:
        r = retriever.retrieve(state["resolved_text"])
        if not r.passed:
            return {"answer": REFUSE_TEXT, "citations": [], "evidence": r, "passed": False}
        cites = build_citations(r.chunks)
        evidence_text = "\n".join(c.snippet for c in r.chunks)
        context = [
            {"role": "user", "content": state["resolved_text"]},
            {"role": "system", "content": "参考资料：\n" + evidence_text},
        ]
        agent_res = run_agent(
            chat_model,
            tools,
            context,
            max_steps=settings.agent_max_steps,
            token_budget=settings.agent_token_budget,
            timeout_s=settings.agent_timeout_s,
        )
        return {"answer": agent_res.answer, "citations": cites, "evidence": r, "passed": True}

    def _fixed_text(state: WorkflowState) -> dict:
        text = FIXED_TEXTS.get(state["branch"], FIXED_TEXTS[Branch.其他])
        return {"answer": text, "citations": []}

    def _honest_stub(state: WorkflowState) -> dict:
        text = HONEST_STUBS.get(state["branch"], HONEST_STUBS[Branch.退款退货])
        return {"answer": text, "citations": []}

    def _final(state: WorkflowState) -> dict:
        return {}

    graph = StateGraph(WorkflowState)
    graph.add_node("resolve", _resolve)
    graph.add_node("classify", _classify)
    graph.add_node("product_qa", _product_qa)
    graph.add_node("fixed_text", _fixed_text)
    graph.add_node("honest_stub", _honest_stub)
    graph.add_node("final", _final)

    graph.add_edge(START, "resolve")
    graph.add_edge("resolve", "classify")
    graph.add_conditional_edges(
        "classify",
        _route_by_branch,
        {
            Branch.商品咨询: "product_qa",
            Branch.闲聊: "fixed_text",
            Branch.投诉: "fixed_text",
            Branch.其他: "fixed_text",
            Branch.退款退货: "honest_stub",
            Branch.售后: "honest_stub",
            Branch.物流订单: "honest_stub",
        },
    )
    graph.add_edge("product_qa", "final")
    graph.add_edge("fixed_text", "final")
    graph.add_edge("honest_stub", "final")
    graph.add_edge("final", END)

    return graph.compile()

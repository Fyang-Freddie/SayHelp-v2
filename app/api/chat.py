import functools
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.api.conversations import get_owned_conversation
from app.config import settings
from app.db import get_db
from app.models import Conversation, Message, User
from app.schemas import ChatStreamRequest, FeedbackRequest, MessageOut
from app.tools.context import build_execution_context
from app.tools.executor import ToolExecutor

router = APIRouter(prefix="/api", tags=["chat"])


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# 服务不可用时的诚实降级（真实「服务暂时不可用」，不伪造任何业务结果）。
SERVICE_UNAVAILABLE_TEXT = "抱歉，服务暂时不可用，请稍后重试。"


class _LazyWorkflow:
    """惰性工作流：首次 ``invoke()`` 时才构建真实模型/检索器（不提前 import 重库）。"""

    def __init__(self, builder) -> None:
        self._builder = builder
        self._graph = None

    def invoke(self, *args, **kwargs):
        if self._graph is None:
            self._graph = self._builder()
        return self._graph.invoke(*args, **kwargs)


class _LazyRetriever:
    """完全惰性检索器：仅首次 ``retrieve()`` 时才 import pymilvus/FlagEmbedding、
    构建 MilvusStore/BGEM3Embedder/BGEReranker 并 ``ensure_collection()``。
    非商品咨询分支与错误路径永不触碰 Milvus。"""

    def __init__(self) -> None:
        self._retriever = None

    def retrieve(self, query, top_k=10):
        if self._retriever is None:
            from app.rag.bge import BGEM3Embedder, BGEReranker
            from app.rag.milvus_store import MilvusStore
            from app.rag.retrieval import Retriever

            store = MilvusStore(settings.milvus_uri)
            store.ensure_collection()
            self._retriever = Retriever(BGEM3Embedder(), store, BGEReranker())
        return self._retriever.retrieve(query, top_k=top_k)


def _build_real_workflow():
    """构建真实工作流。仅在真正运行时才 import langchain_openai（首次 complete/classify），
    检索侧经 ``_LazyRetriever`` 延后到首次 ``retrieve()`` 才 import pymilvus/FlagEmbedding，
    使 404 / 越权路径、闲聊/stub 分支、错误路径与测试永不触发重库导入。"""
    from app.llm.client import OpenAIChatModel, JevIntentModel
    from app.workflow.graph import build_workflow

    chat_model = OpenAIChatModel(settings.chat_base_url, settings.chat_model, settings.chat_api_key)
    intent_model = JevIntentModel()
    return build_workflow(chat_model=chat_model, intent_model=intent_model, retriever=get_retriever())


@functools.lru_cache(maxsize=1)
def get_retriever():
    """检索器工厂依赖：进程内共享的惰性检索器（首次 retrieve() 才 import 重库）。"""
    return _LazyRetriever()


@functools.lru_cache(maxsize=1)
def get_tool_registry():
    """工具注册中心工厂依赖：注册内置工具 + 接入 MCP 客户端（惰性发现）。

    ``lru_cache(maxsize=1)`` 使其成为进程内单例；MCP 工具经 ``McpClient`` 缓存首次
    发现结果，Server 重启后需 ``refresh()``（部署层）。测试经 dependency_overrides
    覆盖为空的 ``ToolRegistry()``，不触真实 MCP 网络。
    """
    from app.mcp.client import McpClient, make_http_transport
    from app.tools.builtin import register_builtin_tools
    from app.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_builtin_tools(registry, retriever=get_retriever())
    registry.attach_mcp(McpClient(make_http_transport()))
    return registry


@functools.lru_cache(maxsize=1)
def get_workflow():
    """工作流工厂依赖：默认惰性构建真实工作流；测试经 dependency_overrides 注入确定性 fake。

    ``lru_cache(maxsize=1)`` 使工作流成为进程内共享的单例惰性实例——首次
    ``invoke()`` 才构建真实模型/检索器，避免每个请求重建全栈并重载 BGE 模型
    （GB 级）。dependency_overrides 会绕过本函数，测试仍确定性。
    """
    return _LazyWorkflow(_build_real_workflow)


def _json_safe(value):
    """把值归一为 JSON-safe（如 chunk_id 为非标量对象时降级为字符串）。"""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _serialize_citations(citations) -> dict:
    """把 Citation 列表序列化为 JSON-safe dict（chunk_id 强制 JSON-safe）。"""
    rows = [
        {
            "index": c.index,
            "chunk_id": _json_safe(c.chunk_id),
            "section_path": c.section_path,
            "category": c.category,
            "content_type": c.content_type,
            "snippet": c.snippet,
        }
        for c in citations
    ]
    return {"citations": rows}


@router.post("/chat/stream")
def chat_stream(req: ChatStreamRequest, db: Session = Depends(get_db),
                user: User = Depends(get_current_user), workflow=Depends(get_workflow),
                registry=Depends(get_tool_registry)):
    conv = get_owned_conversation(req.conversation_id, user, db)
    # 刷新会话活跃时间，保证列表按 updated_at 倒序时最近聊过的会话浮顶
    conv.updated_at = datetime.now(timezone.utc)
    user_msg = Message(conversation_id=conv.id, role="user", content=req.content)
    db.add(user_msg); db.commit()
    db.refresh(user_msg)

    # 加载该会话在本次 user 消息之前的历史（排除刚落的 user 消息），使
    # resolve_reference 指代消解真正看到多轮历史（计划 Goal「真实的多轮问答主链路」）。
    history = [
        {"role": m.role.value, "content": m.content}
        for m in (
            db.query(Message)
            .filter(Message.conversation_id == conv.id, Message.id != user_msg.id)
            .order_by(Message.id)
            .all()
        )
    ]

    # 身份由引擎注入（§4.5）：customer_id 取会话归属客户（owner），工具可见性/执行
    # 权限每请求重新鉴权。agent_tools 只暴露 visible_to_agent 的工具给模型。
    owner = db.get(User, conv.user_id)
    ctx = build_execution_context(caller=user, owner=owner, conversation=conv)
    executor = ToolExecutor(registry, db)
    agent_tools = executor.agent_tools(ctx)

    def gen():
        yield sse_event("status", {"state": "processing"})
        try:
            state = workflow.invoke({"messages": [*history, {"role": "user", "content": req.content}],
                                     "ctx": ctx, "agent_tools": agent_tools})
            answer = state["answer"]
            citations = state.get("citations", [])
            cards = state.get("cards") or []
        except Exception:
            # 工作流异常（如模型/检索器故障）→ 发 error + done，绝不裸断流。
            answer = SERVICE_UNAVAILABLE_TEXT
            citations = []
            cards = []
            yield sse_event("error", {"message": "服务暂时不可用，请稍后重试"})
        else:
            yield sse_event("text", {"delta": answer})
            if citations:
                yield sse_event("reference", _serialize_citations(citations))
            for c in cards:
                yield sse_event("card", c)
        yield sse_event("done", {})

        # 回答（或诚实降级）连同 citations 在流结束后落库为 assistant 消息，
        # 保证 user 消息绝不无 assistant 回应；闸不过/降级时 citations 为空，不伪造。
        assistant = Message(
            conversation_id=conv.id,
            role="assistant",
            content=answer,
            citations=_serialize_citations(citations) if citations else None,
        )
        db.add(assistant); db.commit()

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/messages/{message_id}/feedback", response_model=MessageOut)
def feedback(message_id: int, req: FeedbackRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    msg = db.get(Message, message_id)
    if msg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "消息不存在")
    get_owned_conversation(msg.conversation_id, user, db)
    if req.type not in ("up", "down"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "type 须为 up/down")
    msg.feedback = {"type": req.type, "at": datetime.now(timezone.utc).isoformat()}
    db.commit(); db.refresh(msg)
    return MessageOut.model_validate(msg)

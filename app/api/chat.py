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

router = APIRouter(prefix="/api", tags=["chat"])


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class _LazyWorkflow:
    """惰性工作流：首次 ``invoke()`` 时才构建真实模型/检索器（不提前 import 重库）。"""

    def __init__(self, builder) -> None:
        self._builder = builder
        self._graph = None

    def invoke(self, *args, **kwargs):
        if self._graph is None:
            self._graph = self._builder()
        return self._graph.invoke(*args, **kwargs)


def _build_real_workflow():
    """构建真实工作流。仅在真正运行时才 import langchain_openai / pymilvus / FlagEmbedding，
    使 404 / 越权路径与测试永不触发重库导入（对齐 app/rag/search.py run(real=True) 的懒加载）。"""
    from app.llm.client import OpenAIChatModel, JevIntentModel
    from app.rag.bge import BGEM3Embedder, BGEReranker
    from app.rag.milvus_store import MilvusStore
    from app.rag.retrieval import Retriever
    from app.workflow.graph import build_workflow

    store = MilvusStore(settings.milvus_uri)
    store.ensure_collection()
    retriever = Retriever(BGEM3Embedder(), store, BGEReranker())
    chat_model = OpenAIChatModel(settings.chat_base_url, settings.chat_model, settings.chat_api_key)
    intent_model = JevIntentModel()
    return build_workflow(chat_model=chat_model, intent_model=intent_model, retriever=retriever, tools=[])


def get_workflow():
    """工作流工厂依赖：默认惰性构建真实工作流；测试经 dependency_overrides 注入确定性 fake。"""
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
                user: User = Depends(get_current_user), workflow=Depends(get_workflow)):
    conv = get_owned_conversation(req.conversation_id, user, db)
    # 刷新会话活跃时间，保证列表按 updated_at 倒序时最近聊过的会话浮顶
    conv.updated_at = datetime.now(timezone.utc)
    user_msg = Message(conversation_id=conv.id, role="user", content=req.content)
    db.add(user_msg); db.commit()

    def gen():
        yield sse_event("status", {"state": "processing"})
        state = workflow.invoke({"messages": [{"role": "user", "content": req.content}]})
        answer = state["answer"]
        citations = state.get("citations", [])
        yield sse_event("text", {"delta": answer})
        if citations:
            yield sse_event("reference", _serialize_citations(citations))
        yield sse_event("done", {})

        # 回答连同 citations 在流结束后落库为 assistant 消息（闸不过时 citations 为空，不伪造）。
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

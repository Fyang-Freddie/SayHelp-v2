import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.api.conversations import get_owned_conversation
from app.db import get_db
from app.models import Conversation, Message, User
from app.schemas import ChatStreamRequest, FeedbackRequest, MessageOut

router = APIRouter(prefix="/api", tags=["chat"])

P1_PLACEHOLDER = "你好，我是 SayHelp 客服助手。当前为 P1 骨架阶段，完整问答将在后续阶段接入。"

def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

@router.post("/chat/stream")
def chat_stream(req: ChatStreamRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conv = get_owned_conversation(req.conversation_id, user, db)
    user_msg = Message(conversation_id=conv.id, role="user", content=req.content)
    db.add(user_msg); db.commit()

    def gen():
        yield sse_event("status", {"state": "processing"})
        yield sse_event("text", {"delta": P1_PLACEHOLDER})
        yield sse_event("done", {})

    # 占位回答在流结束后落库为 assistant 消息（P3 会在生成侧落库）
    assistant = Message(conversation_id=conv.id, role="assistant", content=P1_PLACEHOLDER)
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

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import require_role
from app.db import get_db
from app.models import Conversation, Message, User
from app.schemas import ConversationOut, MessageOut

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/conversations", response_model=list[ConversationOut])
def list_waiting(status: str = "agent_waiting", db: Session = Depends(get_db),
                 user: User = Depends(require_role("agent", "admin"))):
    rows = (db.query(Conversation).filter(Conversation.status == status)
            .order_by(Conversation.updated_at.desc()).all())
    return [ConversationOut.model_validate(r) for r in rows]


@router.post("/conversations/{conv_id}/claim", response_model=ConversationOut)
def claim(conv_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("agent", "admin"))):
    conv = db.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    if conv.status != "agent_waiting":
        raise HTTPException(status.HTTP_409_CONFLICT, "会话不在待接入状态")
    conv.status = "agent_connected"
    db.commit(); db.refresh(conv)
    return ConversationOut.model_validate(conv)


@router.post("/conversations/{conv_id}/messages", response_model=MessageOut)
def agent_reply(conv_id: int, body: dict, db: Session = Depends(get_db),
                user: User = Depends(require_role("agent", "admin"))):
    conv = db.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    msg = Message(conversation_id=conv.id, role="assistant", content=body.get("content", ""),
                  sender_id=user.id, sender_name=user.display_name or user.username or "坐席")
    db.add(msg)
    conv.updated_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(msg)
    return MessageOut.model_validate(msg)


@router.post("/conversations/{conv_id}/close", response_model=ConversationOut)
def close(conv_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("agent", "admin"))):
    conv = db.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    conv.status = "ended"
    db.commit(); db.refresh(conv)
    return ConversationOut.model_validate(conv)

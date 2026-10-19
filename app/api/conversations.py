from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import Conversation, Message, User
from app.schemas import ConversationOut, MessageOut

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

@router.get("", response_model=list[ConversationOut])
def list_conversations(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (db.query(Conversation).filter(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc()).limit(limit).offset(offset).all())
    return [ConversationOut.model_validate(r) for r in rows]

@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conv = Conversation(user_id=user.id)
    db.add(conv); db.commit(); db.refresh(conv)
    return ConversationOut.model_validate(conv)

def get_owned_conversation(conv_id: int, user: User, db: Session) -> Conversation:
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    return conv

@router.get("/{conv_id}/messages", response_model=list[MessageOut])
def list_messages(conv_id: int, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    get_owned_conversation(conv_id, user, db)
    rows = (db.query(Message).filter(Message.conversation_id == conv_id)
            .order_by(Message.id.asc()).limit(limit).offset(offset).all())
    return [MessageOut.model_validate(r) for r in rows]

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.chat import get_tool_registry
from app.api.conversations import get_owned_conversation
from app.auth.deps import get_current_user
from app.db import get_db
from app.models import User
from app.schemas import ResumeRequest
from app.tools.context import ExecutionContext
from app.tools.executor import ToolExecutor
from app.tools.interrupt import build_card, sign_interrupt, verify_interrupt

router = APIRouter(prefix="/api/chat", tags=["chat"])

_ACTION_CARD = {"transfer": "transfer_human", "confirm_ticket": "ticket_confirm",
                "select_order": "order_select"}


@router.post("/resume")
def resume(req: ResumeRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user),
           registry=Depends(get_tool_registry)):
    conv = get_owned_conversation(req.conversation_id, user, db)

    if req.action == "cancel":
        return {"status": "cancelled"}
    card_type = _ACTION_CARD.get(req.action)
    if card_type is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "未知 action")
    payload = verify_interrupt(req.interrupt_id, req.conversation_id, card_type)
    if payload is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "interrupt 无效或已过期（防跨会话）")

    owner = db.get(User, conv.user_id)
    ctx = ExecutionContext(caller_user_id=user.id, caller_role=user.role.value,
                           customer_id=owner.customer_id if owner else None,
                           conversation_id=conv.id, confirmed=True)

    if req.action == "transfer":
        conv.status = "agent_waiting"; db.commit()
        return {"status": "transferred"}
    if req.action == "confirm_ticket":
        p = req.payload or {}
        idem = hashlib.sha256(f"ticket:{conv.id}:{payload['nonce']}".encode()).hexdigest()
        # 建工单是写工具，走统一执行引擎（审计 + 写确认 + 统一错误收敛），不绕过 executor。
        out = ToolExecutor(registry, db).execute(
            "create_ticket",
            {"description": p.get("description", ""), "type": p.get("type", "投诉"),
             "idempotency_key": idem},
            ctx,
        )
        return json.loads(out)
    # select_order → 退款预览卡片（D3：不真实提交）
    token, _ = sign_interrupt(conv.id, "refund_preview")
    card = build_card("refund_preview", token, {
        "order_no": (req.payload or {}).get("order_no"),
        "item_id": (req.payload or {}).get("item_id"),
        "notice": "退款未真实提交，如需办理请转人工或建工单。",
    })
    return {"card": card}

import base64
import hashlib
import hmac
import json
import secrets
import time

from app.config import settings

CARD_TYPES = {"order_select", "ticket_confirm", "transfer_human", "refund_preview"}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(msg: str) -> str:
    return _b64(hmac.new(settings.jwt_secret.encode(), msg.encode(), hashlib.sha256).digest())


def sign_interrupt(conversation_id: int, card_type: str, *, ttl_s: int = 1800) -> tuple[str, str]:
    nonce = secrets.token_urlsafe(16)
    payload = {"conversation_id": conversation_id, "card_type": card_type,
               "nonce": nonce, "exp": int(time.time()) + ttl_s}
    body = _b64(json.dumps(payload, ensure_ascii=False).encode())
    return f"{body}.{_sign(body)}", nonce


def verify_interrupt(token: str, conversation_id: int, card_type: str) -> dict | None:
    try:
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(body)):
            return None
        payload = json.loads(_b64d(body))
    except Exception:
        return None
    if payload.get("conversation_id") != conversation_id:
        return None
    if payload.get("card_type") != card_type:
        return None
    if payload.get("exp", 0) < int(time.time()):
        return None
    return payload


def build_card(card_type: str, interrupt_id: str, payload: dict) -> dict:
    return {"type": card_type, "interrupt_id": interrupt_id, "payload": payload}

from app.tools.interrupt import (
    build_card, sign_interrupt, verify_interrupt, CARD_TYPES,
)


def test_sign_and_verify_roundtrip():
    token, nonce = sign_interrupt(conversation_id=7, card_type="ticket_confirm")
    payload = verify_interrupt(token, conversation_id=7, card_type="ticket_confirm")
    assert payload is not None
    assert payload["conversation_id"] == 7
    assert payload["card_type"] == "ticket_confirm"
    assert payload["nonce"] == nonce


def test_verify_rejects_wrong_conversation():
    token, _ = sign_interrupt(7, "transfer_human")
    assert verify_interrupt(token, conversation_id=8, card_type="transfer_human") is None  # 防跨会话


def test_verify_rejects_wrong_card_type():
    token, _ = sign_interrupt(7, "order_select")
    assert verify_interrupt(token, conversation_id=7, card_type="ticket_confirm") is None


def test_verify_rejects_tampered():
    token, _ = sign_interrupt(7, "ticket_confirm")
    assert verify_interrupt(token + "x", conversation_id=7, card_type="ticket_confirm") is None


def test_build_card_shape():
    card = build_card("ticket_confirm", "tok", {"description": "物流慢"})
    assert card == {"type": "ticket_confirm", "interrupt_id": "tok", "payload": {"description": "物流慢"}}


def test_card_types_cover_four():
    assert CARD_TYPES == {"order_select", "ticket_confirm", "transfer_human", "refund_preview"}

from app.llm.client import INTENTS, IntentResult
from app.llm.fakes import FakeChatModel, FakeIntentModel


def test_intents_enum_covers_all_eight():
    assert set(INTENTS) == {"物流", "订单", "商品咨询", "退款退货", "售后", "投诉", "闲聊", "其他"}


def test_fake_chat_model_returns_scripted_text():
    m = FakeChatModel()
    m.next_text = "已改写的问题"
    assert m.complete([{"role": "user", "content": "hi"}]) == "已改写的问题"


def test_fake_chat_model_complete_json_parses():
    m = FakeChatModel()
    m.next_json = {"intent": "退款退货", "confidence": 0.93}
    out = m.complete_json([{"role": "user", "content": "x"}], json_schema={"type": "object"})
    assert out == {"intent": "退款退货", "confidence": 0.93}


def test_fake_intent_model_returns_scripted_result():
    m = FakeIntentModel()
    m.next_result = IntentResult(intent="商品咨询", confidence=0.9)
    r = m.classify("手机保修多久")
    assert r.intent == "商品咨询" and r.confidence == 0.9


def test_fake_chat_model_tracks_calls():
    m = FakeChatModel()
    assert m.called is False
    m.next_text = "x"
    m.complete([{"role": "user", "content": "hi"}])
    assert m.called is True

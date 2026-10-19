from app.llm.client import IntentResult
from app.llm.fakes import FakeIntentModel
from app.workflow.intent import classify_intent


def test_classify_returns_valid_intent():
    m = FakeIntentModel()
    m.next_result = IntentResult(intent="退款退货", confidence=0.93)
    r = classify_intent(m, "我要退货", threshold=0.5)
    assert r.intent == "退款退货" and r.confidence == 0.93


def test_classify_falls_back_on_low_confidence():
    m = FakeIntentModel()
    m.next_result = IntentResult(intent="退款退货", confidence=0.3)
    r = classify_intent(m, "我要退货", threshold=0.5)
    assert r.intent == "其他" and r.confidence == 0.0


def test_classify_falls_back_on_unknown_intent():
    m = FakeIntentModel()
    m.next_result = IntentResult(intent="不存在的类别", confidence=0.9)
    r = classify_intent(m, "x", threshold=0.5)
    assert r.intent == "其他"


def test_classify_falls_back_on_model_error():
    class _Boom:
        def classify(self, text):
            raise RuntimeError("jev 超时")
    r = classify_intent(_Boom(), "x", threshold=0.5)
    assert r.intent == "其他" and r.confidence == 0.0

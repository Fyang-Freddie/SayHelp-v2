from app.llm.fakes import FakeChatModel
from app.workflow.resolve import resolve_reference


def test_resolve_passes_through_when_no_history():
    m = FakeChatModel()
    m.next_text = "不该被调用"
    assert resolve_reference(m, [], "手机保修多久") == "手机保修多久"


def test_resolve_replaces_pronoun_using_scripted_model():
    m = FakeChatModel()
    m.next_text = "请问 MM-CATFOOD2K 这款的保修多久"
    history = [{"role": "user", "content": "我买了宠物主粮 MM-CATFOOD2K"},
               {"role": "assistant", "content": "好的，请问有什么可以帮您？"}]
    assert resolve_reference(m, history, "它的保修多久") == "请问 MM-CATFOOD2K 这款的保修多久"

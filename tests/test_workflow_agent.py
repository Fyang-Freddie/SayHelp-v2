from app.llm.fakes import FakeChatModel
from app.workflow.agent import Tool, run_agent


class _EchoTool:
    name = "echo"
    description = "回显"

    def run(self, args):
        return f"echo:{args.get('s')}"


def test_agent_finalizes_without_tool():
    m = FakeChatModel()
    m.next_text = "最终答案"
    res = run_agent(m, [], [{"role": "user", "content": "hi"}],
                    max_steps=4, token_budget=1000, timeout_s=10)
    assert res.answer == "最终答案" and res.steps == [{"kind": "final", "tool": None, "args": None, "observation": None}]


def test_agent_calls_tool_then_finalizes():
    m = FakeChatModel()
    m.next_actions = [("tool_call", {"name": "echo", "args": {"s": "hi"}}), ("final", "用工具结果作答")]
    res = run_agent(m, [_EchoTool()], [{"role": "user", "content": "hi"}],
                    max_steps=4, token_budget=1000, timeout_s=10)
    assert res.answer == "用工具结果作答"
    assert res.steps[0]["kind"] == "tool_call" and res.steps[0]["observation"] == "echo:hi"


def test_agent_stops_at_max_steps_with_graceful_text():
    m = FakeChatModel()
    m.next_actions = [("tool_call", {"name": "echo", "args": {"s": "x"}})] * 10
    res = run_agent(m, [_EchoTool()], [{"role": "user", "content": "hi"}],
                    max_steps=3, token_budget=1000, timeout_s=10)
    assert "无法" in res.answer or "抱歉" in res.answer  # 诚实降级，不裸抛异常


def test_agent_stops_at_max_steps_with_varying_calls():
    m = FakeChatModel()
    m.next_actions = [("tool_call", {"name": "echo", "args": {"s": f"x{i}"}}) for i in range(10)]
    res = run_agent(m, [_EchoTool()], [{"role": "user", "content": "hi"}],
                    max_steps=3, token_budget=10000, timeout_s=10)
    assert ("无法" in res.answer) or ("抱歉" in res.answer)
    assert len([s for s in res.steps if s["kind"] == "tool_call"]) == 3


def test_agent_stops_on_repeated_ineffective_call():
    m = FakeChatModel()
    m.next_actions = [("tool_call", {"name": "echo", "args": {"s": "x"}}),
                      ("tool_call", {"name": "echo", "args": {"s": "x"}}),
                      ("final", "不该出现")]
    res = run_agent(m, [_EchoTool()], [{"role": "user", "content": "hi"}],
                    max_steps=4, token_budget=10000, timeout_s=10)
    assert ("无法" in res.answer) or ("抱歉" in res.answer)


def test_agent_stops_at_token_budget():
    m = FakeChatModel()
    m.next_actions = [("final", "不该出现")]
    res = run_agent(m, [], [{"role": "user", "content": "x" * 5000}],
                    max_steps=4, token_budget=1000, timeout_s=10)
    assert ("无法" in res.answer) or ("抱歉" in res.answer)


def test_agent_stops_at_timeout(monkeypatch):
    state = {"n": 0}

    def fake_monotonic():
        state["n"] += 1
        return 0.0 if state["n"] == 1 else 9999.0

    monkeypatch.setattr("app.workflow.agent.monotonic", fake_monotonic)
    m = FakeChatModel()
    m.next_actions = [("final", "不该出现")]
    res = run_agent(m, [], [{"role": "user", "content": "hi"}],
                    max_steps=4, token_budget=10000, timeout_s=10)
    assert ("无法" in res.answer) or ("抱歉" in res.answer)

"""确定性 fakes：脚本化输出，供 P3 后续任务与测试复用。

- ``FakeChatModel``：脚本 ``next_actions`` / ``next_text`` / ``next_json`` +
  ``called`` 布尔。``next_actions`` 为 ``[("tool_call", {"name","args"}) |
  ("final", text)]`` 队列，``complete_json`` 按 next_actions → next_text →
  next_json 顺序回落（Task 5 增补）。
- ``FakeIntentModel``：脚本 ``next_result``。
"""
from __future__ import annotations

from app.llm.client import IntentResult


class FakeChatModel:
    def __init__(self):
        self.next_actions: list = []
        self.next_text: str | None = None
        self.next_json: dict | None = None
        self.called: bool = False

    def complete(self, messages: list[dict]) -> str:
        self.called = True
        return self.next_text

    def complete_json(self, messages: list[dict], json_schema: dict) -> dict:
        self.called = True
        if self.next_actions:
            kind, payload = self.next_actions.pop(0)
            if kind == "tool_call":
                return {"action": "tool_call", "tool": payload["name"], "args": payload["args"]}
            return {"action": "final", "text": payload}   # kind == "final"
        if self.next_text is not None:
            return {"action": "final", "text": self.next_text}
        return self.next_json


class FakeIntentModel:
    def __init__(self):
        self.next_result: IntentResult = IntentResult(intent="其他", confidence=0.0)

    def classify(self, text: str) -> IntentResult:
        return self.next_result

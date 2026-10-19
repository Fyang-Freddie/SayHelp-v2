"""确定性 fakes：脚本化输出，供 P3 后续任务与测试复用。

- ``FakeChatModel``：脚本 ``next_text`` / ``next_json`` + ``called`` 布尔；
  ``next_actions`` 能力在 Task 5 增补（YAGNI，本任务不实现）。
- ``FakeIntentModel``：脚本 ``next_result``。
"""
from __future__ import annotations

from app.llm.client import IntentResult


class FakeChatModel:
    def __init__(self):
        self.next_text: str = ""
        self.next_json: dict = {}
        self.called: bool = False

    def complete(self, messages: list[dict]) -> str:
        self.called = True
        return self.next_text

    def complete_json(self, messages: list[dict], json_schema: dict) -> dict:
        self.called = True
        return self.next_json


class FakeIntentModel:
    def __init__(self):
        self.next_result: IntentResult = IntentResult(intent="其他", confidence=0.0)

    def classify(self, text: str) -> IntentResult:
        return self.next_result

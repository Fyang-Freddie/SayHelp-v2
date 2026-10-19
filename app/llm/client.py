"""统一模型客户端：ChatModel / IntentModel 协议 + 两个懒加载真实实现。

导入本模块、构造实例均不 import langchain_openai；首次调用 ``complete()`` /
``complete_json()`` / ``classify()`` 时才延迟导入并实例化 ``ChatOpenAI``，
因此未安装 langchain-openai 时 ``import app.llm.client`` 也能成功（测试只构造
fakes，从不实例化这两个真实模型）。

API 依据 langchain-openai 1.7.2 官方源码/文档核实，见 dev-notes/ch07.md。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# 意图全集（顺序固定，供意图识别/分流复用）。
INTENTS: tuple[str, ...] = (
    "物流",
    "订单",
    "商品咨询",
    "退款退货",
    "售后",
    "投诉",
    "闲聊",
    "其他",
)


@dataclass
class IntentResult:
    intent: str
    confidence: float


class ChatModel(Protocol):
    def complete(self, messages: list[dict]) -> str: ...

    def complete_json(self, messages: list[dict], json_schema: dict) -> dict: ...


class IntentModel(Protocol):
    def classify(self, text: str) -> IntentResult: ...


class OpenAIChatModel:
    """OpenAI 兼容端点上的聊天模型（懒加载 ``langchain_openai.ChatOpenAI``）。

    ``complete_json`` 走 ``with_structured_output(json_schema)``：返回的 runnable
    以 ``.invoke(messages)`` 调用，传入 JSON Schema（dict）时返回 dict。
    """

    def __init__(self, base_url: str, model: str, api_key: str):
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from langchain_openai import ChatOpenAI

            self._llm = ChatOpenAI(
                model=self.model,
                base_url=self.base_url,
                api_key=self.api_key,
                use_responses_api=False,
            )
        return self._llm

    def complete(self, messages: list[dict]) -> str:
        return self._get_llm().invoke(messages).content

    def complete_json(self, messages: list[dict], json_schema: dict) -> dict:
        structured = self._get_llm().with_structured_output(json_schema)
        return structured.invoke(messages)


# 意图识别的输出 Schema：intent 必须是 INTENTS 之一，confidence 为 0..1 数值。
INTENT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "confidence": {"type": "number"},
    },
    "required": ["intent", "confidence"],
}

INTENT_SYSTEM_PROMPT = (
    "你是电商智能客服的意图识别器。请判断用户消息的意图，"
    "从以下类别中恰好选择一个：物流、订单、商品咨询、退款退货、售后、投诉、闲聊、其他。"
    "同时给出 0 到 1 之间的置信度（0 表示完全不确定，1 表示完全确定）。"
)


class JevIntentModel:
    """意图识别模型：指向 jev（OpenAI 兼容）端点，懒加载 ``ChatOpenAI``。

    构造与调用前均不 import langchain_openai；``classify()`` 首次调用时才实例化
    底层模型，并用 ``with_structured_output(INTENT_SCHEMA)`` 得到 dict 后包装为
    ``IntentResult``。超时来自 ``settings.intent_timeout_s``。
    """

    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from langchain_openai import ChatOpenAI

            from app.config import settings

            self._llm = ChatOpenAI(
                model=settings.jev_model,
                base_url=settings.jev_base_url,
                api_key=settings.jev_api_key,
                timeout=settings.intent_timeout_s,
                use_responses_api=False,
            )
        return self._llm

    def classify(self, text: str) -> IntentResult:
        messages = [
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
        structured = self._get_llm().with_structured_output(INTENT_SCHEMA)
        data = structured.invoke(messages)
        return IntentResult(
            intent=data["intent"],
            confidence=float(data["confidence"]),
        )

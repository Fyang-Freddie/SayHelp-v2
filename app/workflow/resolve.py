"""指代消解 + 口语归一（RESOLVE）节点。

把用户话里的指代、省略、口语补齐成一个完整、独立、无歧义的问题，
供后续意图识别与检索使用。空历史时直接原样返回，不调用模型。
"""
from __future__ import annotations

from app.llm.client import ChatModel

RESOLVE_SYSTEM_PROMPT = (
    "把用户话里的指代、省略、口语补齐成一个完整、独立、无歧义的问题；"
    "只输出改写后的问题本身，不要回答、不要解释、不要加引号或前缀。"
)


def resolve_reference(chat_model: ChatModel, history: list[dict], current_text: str) -> str:
    if not history:
        return current_text
    messages = [{"role": "system", "content": RESOLVE_SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": current_text})
    return chat_model.complete(messages)

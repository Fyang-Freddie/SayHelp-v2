"""受控 ReAct Agent 循环（AGENT 节点）。

主力模型在「调用工具」与「给出最终回答」之间循环，受步数上限 / token 预算 /
超时 / 连续重复无效调用四重约束。任何异常（工具名非法、参数畸形、模型返回
畸形、工具抛异常、预算/超时/步数耗尽）一律收敛为诚实降级文本，绝不裸抛异常。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

from app.llm.client import ChatModel

logger = logging.getLogger(__name__)

# 每步决策的统一 JSON Schema（Ruling 7）：模型只能输出 tool_call 或 final。
AGENT_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["tool_call", "final"]},
        "tool": {"type": ["string", "null"]},
        "args": {"type": ["object", "null"]},
        "text": {"type": ["string", "null"]},
    },
    "required": ["action"],
}

# 系统提示（模块常量）：工具清单由 run_agent 逐个追加 name/description。
AGENT_SYSTEM_PROMPT = (
    "你是 SayHelp 电商智能客服 Agent。"
    "你可以调用工具查询订单、物流、商品等信息，也可以直接回答。"
    "需要查信息时，输出 action=tool_call 并给出 tool（工具名）与 args（参数）；"
    "已经能回答时，输出 action=final 并给出 text（最终回答）。"
    "不得编造任何事实或数据。"
    "回答中引用参考资料时，须在句内用 `[n]` 标注对应编号（n 与参考资料编号一致），"
    "且不得杜撰超出所给参考资料的编号。\n"
    "可用工具：\n"
)

# 诚实降级文本（同时含「抱歉」与「无法」）。
DEGRADE_ANSWER = "抱歉，当前无法完成该请求，请稍后重试或转人工（转人工将在后续阶段提供）。"


class Tool(Protocol):
    name: str
    description: str

    def run(self, args: dict) -> str: ...


@dataclass
class AgentResult:
    answer: str
    steps: list[dict]


def _estimate_tokens(messages: list[dict]) -> int:
    """字符数代理估算 token（真实 tokenizer 归 P5）。"""
    return sum(len(str(m.get("content", ""))) for m in messages)


def _degrade(steps: list[dict], reason: str) -> AgentResult:
    logger.warning("agent 收敛：%s", reason)
    return AgentResult(answer=DEGRADE_ANSWER, steps=steps)


def run_agent(
    chat_model: ChatModel,
    tools: list[Tool],
    context_messages: list[dict],
    *,
    max_steps: int,
    token_budget: int,
    timeout_s: float,
) -> AgentResult:
    tools_text = "\n".join(f"- {t.name}: {t.description}" for t in tools)
    messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT + tools_text}]
    messages.extend(context_messages)
    deadline = monotonic() + timeout_s
    last_call = None
    steps: list[dict] = []

    for _ in range(max_steps):
        if monotonic() > deadline:
            return _degrade(steps, "超时")
        if _estimate_tokens(messages) > token_budget:
            return _degrade(steps, "token 预算耗尽")

        try:
            decision = chat_model.complete_json(messages, AGENT_DECISION_SCHEMA)
        except Exception as exc:  # 模型抛异常：降级收敛，不裸抛
            logger.warning("agent complete_json 失败：%s", exc)
            return _degrade(steps, f"无法解析模型决策：{exc}")

        if not isinstance(decision, dict):
            return _degrade(steps, "无法解析模型决策")

        action = decision.get("action")
        if action == "final":
            answer = str(decision.get("text") or "")
            steps.append({"kind": "final", "tool": None, "args": None, "observation": None})
            return AgentResult(answer, steps)

        if action == "tool_call":
            tool_name = decision.get("tool")
            args = decision.get("args") or {}
            tool = next((t for t in tools if t.name == tool_name), None)
            if tool is None:
                return _degrade(steps, f"未知工具 {tool_name}")

            call_key = (tool_name, json.dumps(args, sort_keys=True, ensure_ascii=False))
            if call_key == last_call:
                return _degrade(steps, "重复无效调用")

            try:
                observation = tool.run(args)
            except Exception as exc:
                logger.warning("agent 工具执行失败：%s", exc)
                return _degrade(steps, f"工具执行失败 {exc}")

            steps.append({"kind": "tool_call", "tool": tool_name, "args": args, "observation": observation})
            messages.append({"role": "assistant", "content": f"调用工具 {tool_name}：{json.dumps(args, ensure_ascii=False)}"})
            messages.append({"role": "tool", "content": str(observation)})
            last_call = call_key
            continue

        return _degrade(steps, "无法解析模型决策")

    return _degrade(steps, "达到最大步数")

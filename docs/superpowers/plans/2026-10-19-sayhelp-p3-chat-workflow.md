# SayHelp P3 — 指代消解 + jev 意图 + 确定性分流 + 受控 ReAct Agent 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 P1 的 SSE 占位回答替换为真实的多轮问答主链路：`指代消解 → jev 意图识别 → 代码确定性分流 → 主力模型受控 ReAct 循环 → 流式回答 + 引用`，商品咨询分支端到端跑通，其余分支如实分流并在未接线处诚实降级。

**Architecture:** LangGraph 图（`START → resolve → intent → route → 分支节点 → agent/fixed-text → final`）编排；`app/llm/` 统一 OpenAI 兼容客户端（`deepseek-flash` 负责主力/指代，`jev` 负责意图，各自独立 Prompt 与 Schema）；分流为纯函数；受控 Agent 循环以手写最小循环实现（预算/步数/超时/重复无效调用/停止条件），真实工具与执行引擎在 P4 接入。

**Tech Stack:** Python 3.13.9、FastAPI、LangGraph + langchain-core + langchain-openai（结构化输出 `with_structured_output`）、pydantic v2、复用 P2 的 `app/rag/`（检索+闸+引用）。真实模型走 OpenAI 兼容 HTTP；测试全用确定性 fake，无网络依赖。

**Spec:** `docs/superpowers/specs/2026-10-19-sayhelp-architecture.md`（§4.1–4.5、§5）；阶段边界见 `dev-notes/00-inventory-and-plan.md` §4。

## Global Constraints

- 不伪造业务数据、不随机生成嵌入/检索/意图/答案结果；未接线的分支（退款退货/售后/物流订单）如实返回「该能力后续阶段接入」，不伪造成功、不冒报成功。
- 不冒充真人坐席：转人工/建工单按钮属 P4，P3 仅占位不实现。
- `.env` 只提交 `.env.example`，不提交真实密钥；jev 端点/密钥仍待用户提供（Q1 阻塞），P3 按 OpenAI 兼容协议实现 + `.env` 占位 + 确定性 fake 测试。
- 不伪造库接口：LangGraph / langchain-core / langchain-openai 的 API 与版本在实现时用 WebFetch 核实，并记录 `dev-notes/ch07.md`（沿用 ch06 红线）。
- 模型角色（D4）：主力/指代消解/Query扩写/摘要/裁判统一 `deepseek-flash`（各自独立 Prompt 与 Schema）；jev 独立。Query扩写/摘要/裁判在后续阶段落地，本阶段只接主力 + 指代 + jev。
- 意图枚举（§4.1）：`物流 / 订单 / 商品咨询 / 退款退货 / 售后 / 投诉 / 闲聊 / 其他`；只输出 `intent`、`confidence` 两字段；结构错误/超时/低置信度 → 兜底「其他」并记录，不强塞类别。

## Review Focus

1. **指代消解不得改写原意**：历史为空或单轮时，`resolve` 必须原样透传当前问题，不得由 fake 或模型凭空补写。测试钉住 `history=[] → 原样返回`。
2. **意图兜底穷尽**：jev 返回非法 intent、结构错误、超时、低置信度时，`classify_intent` 必须返回「其他」且不抛异常，不得把未识别的 intent 漏进路由导致图挂起。
3. **分流穷尽**：8 个意图每个都有确定去向（`物流`、`订单` 都进 `物流订单` 支），`route` 对未知 intent 抛明确错误或兜底「其他」，不得返回 None 造成图无条件边。
4. **Agent 循环收敛**：达到最大步数/token 预算/超时/重复无效调用检测时，`run_agent` 给出确定回答或诚实降级文本，不无限循环、不裸 traceback。
5. **商品咨询闸不过诚实拒答**：`evidence_confidence` 未过闸时返回「暂无法确认」类诚实回答，不编造证据；引用 `[n]` 与证据快照一一对应、无悬空编号。

---

## 任务概览与依赖

| 任务 | 交付 | 消费 | 产出 |
|---|---|---|---|
| 1 | `app/llm/` 客户端 + 结构化输出 + fakes | settings（CHAT_*/JEV_*） | `ChatModel`/`IntentModel` 协议、`IntentResult`、`FakeChatModel`/`FakeIntentModel`、`INTENTS` |
| 2 | 指代消解 `resolve` | Task 1 `ChatModel` | `resolve_reference(chat_model, history, text) -> str` |
| 3 | jev 意图 `intent` | Task 1 `IntentModel` | `classify_intent(intent_model, text, threshold) -> IntentResult` |
| 4 | 确定性分流 `route` | 意图枚举 | `Branch`、`route(intent) -> Branch` |
| 5 | 受控 ReAct 循环 | Task 1 `ChatModel`、`Tool` 协议 | `run_agent(chat_model, tools, ctx, budget) -> AgentResult` |
| 6 | LangGraph 图组装 | Task 2–5 | `build_workflow(...) -> CompiledGraph` |
| 7 | SSE 主链路接线 | Task 6 图 + P2 `Retriever`/`build_citations` | `app/api/chat.py` 真实流式回答 |

---

### Task 1: `app/llm/` — 统一模型客户端 + 结构化输出 + 确定性 fakes

**Files:**
- Create: `app/llm/__init__.py`、`app/llm/client.py`、`app/llm/fakes.py`
- Modify: `app/config.py`（新增意图/超时相关设置）
- Test: `tests/test_llm.py`

**Interfaces:**
- Produces:
  - `ChatModel`（Protocol）：`complete(messages: list[dict]) -> str`、`complete_json(messages: list[dict], json_schema: dict) -> dict`
  - `IntentModel`（Protocol）：`classify(text: str) -> IntentResult`
  - `@dataclass IntentResult`：`intent: str`、`confidence: float`
  - `INTENTS: tuple[str, ...] = ("物流", "订单", "商品咨询", "退款退货", "售后", "投诉", "闲聊", "其他")`
  - `OpenAIChatModel`（实现 `ChatModel`，构造参数 `base_url/model/api_key`，懒加载 langchain-openai `ChatOpenAI`，`complete_json` 走 `with_structured_output`）
  - `JevIntentModel`（实现 `IntentModel`，同上懒加载，指向 jev 端点）
  - `FakeChatModel`（脚本 `next_text`/`next_json` + `called` 布尔记录是否被调用；`next_actions` 能力在 Task 5 增补）、`FakeIntentModel`（脚本 `next_result`）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_llm.py
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
```

- [ ] **Step 2: 运行确认失败**（`ModuleNotFoundError: No module named 'app.llm'`）
- [ ] **Step 3: 实现**（协议 + `IntentResult` + 两个懒加载真实模型 + 两个确定性 fake；config 新增 `intent_timeout_s: float = 10`。真实模型类仅保留懒加载构造，不在测试里实例化）
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `feat(p3): unified LLM client with structured output + fakes`

---

### Task 2: 指代消解 + 口语归一（RESOLVE）

**Files:**
- Create: `app/workflow/__init__.py`、`app/workflow/resolve.py`
- Test: `tests/test_workflow_resolve.py`

**Interfaces:**
- Consumes: `ChatModel`（Task 1）
- Produces: `resolve_reference(chat_model: ChatModel, history: list[dict], current_text: str) -> str`
  - `history` 为最近层对话（`[{"role": "user"/"assistant", "content": ...}]`）；**空历史直接原样返回 `current_text`**。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_workflow_resolve.py
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
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**（空历史短路；否则拼 system 提示「把指代/口语补齐为完整独立问题，只输出改写后的问题，不回答」+ history + 当前问题，调 `chat_model.complete`）
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `feat(p3): coreference resolution + colloquial normalization`

---

### Task 3: jev 意图识别（INTENT）

**Files:**
- Create: `app/workflow/intent.py`
- Modify: `app/config.py`（新增 `intent_confidence_threshold: float = 0.5`）
- Test: `tests/test_workflow_intent.py`

**Interfaces:**
- Consumes: `IntentModel`、`INTENTS`（Task 1）
- Produces: `classify_intent(intent_model: IntentModel, text: str, *, threshold: float) -> IntentResult`
  - 兜底语义：`intent` 不在 `INTENTS`、结构错误、异常 → `IntentResult("其他", 0.0)`；`confidence < threshold` → `IntentResult("其他", 0.0)`（记录 reason，P3 内打印/记日志即可，飞轮归集 P6）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_workflow_intent.py
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
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**（try/except 包裹 `intent_model.classify`；校验 intent ∈ `INTENTS` 与 confidence 阈值；失败走「其他」）
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `feat(p3): jev intent classification with honest fallback`

---

### Task 4: 确定性分流（ROUTE）

**Files:**
- Create: `app/workflow/route.py`
- Test: `tests/test_workflow_route.py`

**Interfaces:**
- Consumes: `INTENTS`（Task 1）
- Produces:
  - `class Branch(str, Enum)`：`商品咨询`、`退款退货`、`售后`、`物流订单`、`投诉`、`闲聊`、`其他`
  - `route(intent: str) -> Branch`（`物流`、`订单` → `Branch.物流订单`；未知 intent → `Branch.其他`）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_workflow_route.py
import pytest
from app.workflow.route import Branch, route


@pytest.mark.parametrize("intent,expected", [
    ("商品咨询", Branch.商品咨询),
    ("退款退货", Branch.退款退货),
    ("售后", Branch.售后),
    ("物流", Branch.物流订单),
    ("订单", Branch.物流订单),
    ("投诉", Branch.投诉),
    ("闲聊", Branch.闲聊),
    ("其他", Branch.其他),
    ("不存在", Branch.其他),
])
def test_route_maps_every_intent(intent, expected):
    assert route(intent) is expected
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**（纯函数；`Branch` 枚举 + 映射表 + 未知兜底）
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `feat(p3): deterministic intent routing`

---

### Task 5: 受控 ReAct Agent 循环

**Files:**
- Create: `app/workflow/agent.py`
- Modify: `app/config.py`（新增 `agent_max_steps: int = 6`、`agent_token_budget: int = 8000`、`agent_timeout_s: float = 60`）
- Modify: `app/llm/fakes.py`（`FakeChatModel` 增补 `next_actions` 脚本能力：`[("tool_call", {"name","args"}) | ("final", text)]`）
- Test: `tests/test_workflow_agent.py`

**Interfaces:**
- Consumes: `ChatModel`（Task 1）
- Produces:
  - `class Tool(Protocol)`：`name: str`、`description: str`、`run(args: dict) -> str`
  - `@dataclass AgentResult`：`answer: str`、`steps: list[dict]`（每步 `{"kind": "tool_call"|"final", "tool": str|None, "args": dict|None, "observation": str|None}`）
  - `run_agent(chat_model, tools: list[Tool], context_messages: list[dict], *, max_steps: int, token_budget: int, timeout_s: float) -> AgentResult`
  - 控制规则：步数上限 / token 预算 / 超时 / 连续重复无效调用检测 / 到达上限可理解收敛（返回确定回答或诚实降级文本）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_workflow_agent.py
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
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**（手写最小工具循环：模型决定 `tool_call` 或 `final`；`tool_call` 校验工具名/参数、执行、把 observation 回灌消息、检测重复无效调用；`final` 结束；上限收敛。`FakeChatModel` 增补 `next_actions` 脚本能力以驱动两种动作）
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `feat(p3): controlled ReAct agent loop`

---

### Task 6: LangGraph 工作流组装

**Files:**
- Create: `app/workflow/graph.py`
- Modify: `requirements.txt`（新增 `langgraph`、`langchain-core`、`langchain-openai`；实现时 WebFetch 核实版本后钉定，记录 `dev-notes/ch07.md`）
- Test: `tests/test_workflow_graph.py`

**Interfaces:**
- Consumes: Task 2 `resolve_reference`、Task 3 `classify_intent`、Task 4 `route`/`Branch`、Task 5 `run_agent`；P2 `Retriever`/`build_citations`
- Produces: `build_workflow(*, chat_model, intent_model, retriever, tools, settings) -> CompiledGraph`
  - State 含 `messages`（`add_messages` reducer）、`resolved_text`、`intent_result`、`branch`、`evidence`、`passed`、`answer`、`citations`。
  - 节点：`resolve` → `classify` → 条件边按 `Branch` 分流 →（`商品咨询`：RAG→闸→agent）/（`闲聊`/`投诉`/`其他`：固定话术）/（`退款退货`/`售后`/`物流订单`：诚实占位）→ `final`。
  - `final` 输出 `answer` + `citations`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_workflow_graph.py
from app.llm.fakes import FakeChatModel, FakeIntentModel
from app.llm.client import IntentResult
from app.workflow.graph import build_workflow


class _Rag:
    def retrieve(self, query, top_k=10):
        from app.rag.retrieval import RetrievalResult, ScoredChunk
        return RetrievalResult(
            chunks=[ScoredChunk(chunk_id=1, score=0.9, category="售后政策",
                                section_path="售后政策 > A06【保修期限】",
                                content_type="manual", snippet="手机 12 个月")],
            evidence_confidence=0.9, passed=True)


def test_graph_chitchat_returns_fixed_text_without_model():
    intent = FakeIntentModel(); intent.next_result = IntentResult(intent="闲聊", confidence=0.9)
    chat = FakeChatModel(); chat.next_text = "不该被调用"
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_Rag(), tools=[])
    out = graph.invoke({"messages": [{"role": "user", "content": "你好"}]})
    assert "SayHelp" in out["answer"]
    assert chat.called is False  # 闲聊不调用主力模型


def test_graph_product_qa_end_to_end():
    intent = FakeIntentModel(); intent.next_result = IntentResult(intent="商品咨询", confidence=0.9)
    chat = FakeChatModel(); chat.next_text = "该商品保修 12 个月"
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_Rag(), tools=[])
    out = graph.invoke({"messages": [{"role": "user", "content": "手机保修多久"}]})
    assert out["answer"] == "该商品保修 12 个月"
    assert [c.index for c in out["citations"]] == [1]


def test_graph_logistics_returns_honest_stub():
    intent = FakeIntentModel(); intent.next_result = IntentResult(intent="物流", confidence=0.9)
    chat = FakeChatModel(); chat.next_text = "不该被调用"
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_Rag(), tools=[])
    out = graph.invoke({"messages": [{"role": "user", "content": "我的快递到哪了"}]})
    assert "后续" in out["answer"] or "暂" in out["answer"]  # 诚实降级，不伪造物流结果


def test_graph_product_qa_refuses_when_gate_fails():
    from app.rag.retrieval import RetrievalResult

    class _RagFail:
        def retrieve(self, query, top_k=10):
            return RetrievalResult(chunks=[], evidence_confidence=0.1, passed=False)

    intent = FakeIntentModel(); intent.next_result = IntentResult(intent="商品咨询", confidence=0.9)
    chat = FakeChatModel(); chat.next_text = "不该被调用"
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_RagFail(), tools=[])
    out = graph.invoke({"messages": [{"role": "user", "content": "手机保修多久"}]})
    assert "暂" in out["answer"] or "无法" in out["answer"]  # 闸不过诚实拒答
    assert out["citations"] == []  # 未过闸不得编造引用
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**（LangGraph `StateGraph` + `add_node`/`add_edge`/`add_conditional_edges` + `add_messages` reducer；固定话术与诚实占位文本常量集中定义。**实现前 WebFetch 核实 LangGraph 当前稳定版 API 与 `create_react_agent`/`add_messages` 导入路径，记录 dev-notes/ch07.md**）
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `feat(p3): LangGraph workflow assembly`

---

### Task 7: SSE 主链路接线 + 商品咨询端到端

**Files:**
- Modify: `app/api/chat.py`（替换 P1 占位）、`app/schemas.py`（如需要）
- Test: `tests/test_chat_workflow_api.py`

**Interfaces:**
- Consumes: Task 6 `build_workflow`、P1 已有 `get_current_user`/`get_owned_conversation`/`sse_event`
- Produces: `POST /api/chat/stream` 真实流式（事件 `text`/`status`/`reference`/`done`），回答落库为 assistant 消息并写 `citations`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_chat_workflow_api.py
# 复用 conftest 的测试客户端 + 登录态；注入确定性 workflow（FakeIntent/FakeChat/FakeRag）
def test_chat_stream_chitchat_returns_fixed_text(client, auth_headers):
    r = client.post("/api/chat/stream", json={"conversation_id": 1, "content": "你好"},
                    headers=auth_headers)
    body = r.text
    assert "event: done" in body
    assert "SayHelp" in body


def test_chat_stream_product_qa_returns_reference(client, auth_headers):
    r = client.post("/api/chat/stream", json={"conversation_id": 1, "content": "手机保修多久"},
                    headers=auth_headers)
    assert "event: reference" in r.text
    assert "event: done" in r.text
```

- [ ] **Step 2: 运行确认失败**（现为 P1 占位，无 `reference` 事件）
- [ ] **Step 3: 实现**（在请求内构建 `build_workflow`（注入 fake/真实模型按 settings），逐节点流式产出 `status`/`text`/`reference`/`done`；assistant 消息连同 `citations` 落库；商品咨询走 RAG→闸→agent，闸不过返回诚实拒答）
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `feat(p3): wire real chat workflow into SSE stream`

---

## 完成验收（P3）

- `python -m pytest` 全套通过（新增 llm/workflow 测试全用确定性 fake，无网络/无模型下载依赖）。
- `POST /api/chat/stream` 真实走 `指代消解 → 意图 → 分流 → 分支`：
  - 闲聊/投诉/其他 → 固定话术（闲聊不调用主力模型）；
  - 商品咨询 → RAG 检索 → 证据闸 → 主力模型回答 + 引用（端到端）；
  - 退款退货/售后/物流订单 → 正确分流 + 诚实「后续阶段接入」占位。
- 意图低置信度/结构错误/超时 → 兜底「其他」不崩；Agent 到达预算上限可理解收敛。
- jev 真实端点仍待用户提供（Q1）：按 OpenAI 兼容协议 + `.env` 占位实现，`.env.example` 不提交真实密钥；LangGraph 等库接口经 WebFetch 核实并记录 `dev-notes/ch07.md`。

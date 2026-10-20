# SayHelp P4：工具执行引擎 / 内置工具 / 两个 MCP / 卡片与转人工 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 P3 的诚实占位（退款退货/售后/物流订单/投诉）替换为真实可运行的「统一工具执行引擎 + 内置工具 + 两个 MCP Server + 转人工/建工单/订单选择/退款预览卡片」，并对每一次工具执行落 `tool_audit_logs` 审计。

**Architecture:** 工具全部经一个统一执行引擎（鉴权→归属校验→执行→审计→回灌观察），身份（`ExecutionContext`）由引擎隐藏注入、绝不进入模型可见的工具 Schema / 消息。内置工具（`query_order`/`query_product`/`query_faq`/`create_ticket`）直连 MySQL；两个 MCP Server（物流 `query_logistics`、售后 `query_warranty`/`query_return_progress`）作为独立进程用 `mcp` SDK 暴露工具，客服服务的 MCP 客户端每请求动态发现。卡片走无 checkpointer 的「有状态 resume」：SSE `card` 事件携带 HMAC 签名的 `interrupt_id`，`POST /api/chat/resume` 校验归属 + 幂等 + 防跨会话后动作；转人工用 `conversations.status` 状态机（`open → agent_waiting → agent_connected → ended`）+ role=agent 接单端点，坐席身份经新增 `messages.sender_name` 如实标注。

**Tech Stack:** Python 3.13.9 / FastAPI / SQLAlchemy 2.0 / LangGraph 1.2.12（P3 已钉）/ `mcp` Python SDK（版本实施时经 PyPI JSON + 已装包内省核实，记录 dev-notes/ch08.md）。

**Spec:** `docs/superpowers/specs/2026-10-19-sayhelp-architecture.md`（§3.3/§3.5、§4.3/§4.4/§4.5/§4.6、§5）；阶段边界 `dev-notes/00-inventory-and-plan.md` §4。

## Global Constraints

（每一条都隐含进每个任务的验收；来自 spec + 已锁定决策 + 安全红线，逐字执行。）

- **不伪造业务数据 / 不冒充真人 / 不谎称接通或已提交**：退款只做表单预览并明确提示「退款未真实提交」；转人工坐席身份如实标注（`sender_name`）；仅 `create_ticket` 为写工具。
- **身份由引擎注入**（§4.5）：`user_id`/`customer_id`/权限只存在于执行上下文，不出现在工具 JSON Schema、System Prompt、模型消息、工具结果里；工具可见性与执行权限分离，每轮/resume 重新鉴权。
- **不伪造库接口**：`mcp` SDK 及其他第三方库接口须核实后记录 `dev-notes/ch08.md`；核实不到就如实说明，不用记忆硬写接口。
- **测试确定性、无网络**：pytest 用 SQLite 内存库 + 确定性 fake，不触网、不触真模型、不触真 Milvus/MCP 子进程。测试要覆盖 `get_workflow` 与 `get_tool_registry` 两个依赖的覆盖（见 Task 10）。
- **主力模型 deepseek-flash**（OpenAI 兼容，`.env` 的 `CHAT_*`）；**jev 独立且 P4 不碰**（P3 遗留的 jev System One 协议差异不在本阶段范围，见计划末「范围外」）。
- **`.env` 不提交真实密钥**；`.env.example` 同步新增字段但不含真实值。
- 模型角色：主力/指代消解/扩写/摘要/裁判统一 `deepseek-flash`；Python 3.13.9；中文沟通。
- **迁移纪律**（P0 已锁定，见 memory）：冻结迁移 `0001_initial.py` 是本项目「全量快照」；增列须同步改模型 + `0001_initial.py` 的 `messages` DDL 字符串（本项目预发布、Docker/MySQL 未常驻，按 squash 约定，不新增 0002）。

## Review Focus

以下 5 类输入/失败模式是 spec 隐含、但若任务测试不写就没人测的坑，最可能咬到真实使用者。每条都在「拥有该代码的任务」里加测试钉住。

1. **越权查询**：客户 A 用 `query_order`/物流工具查客户 B 的订单 → 必须空结果或权限拒绝（`customer_id` 归属过滤，注入到引擎而非参数；MCP 工具在引擎侧按 `ownership_field` 预检）。
2. **建工单重复提交**：同一确认卡片双击/重放 resume → 幂等，只落一张工单（`tickets.idempotency_key` 唯一约束）。
3. **跨会话 resume**：拿会话 A 的 `interrupt_id` 去 resume 会话 B → 拒绝（签名绑定 conversation_id + 归属校验）。
4. **工具重名/旧物流工具**：`query_logistics` 只来自 MCP（source=mcp），内置工具不得有同名抢注册；物流查询绝不再走占位话术。
5. **转人工身份**：agent 接管后消息须带 `sender_name`（如「坐席 王小明」），前端可区分真人 vs AI，绝不把坐席回复冒充为 AI 回答。

---

## 文件结构

**新建：**
- `app/tools/__init__.py`
- `app/tools/context.py` — `ExecutionContext` + `build_execution_context`（身份注入）
- `app/tools/registry.py` — `ToolSpec` / `ToolRegistry` / `AgentTool`（注册中心）
- `app/tools/executor.py` — `ToolExecutor`（鉴权→归属校验→执行→审计→观察）
- `app/tools/builtin.py` — `query_order` / `query_product` / `query_faq` / `create_ticket` 处理器 + 注册
- `app/tools/interrupt.py` — `sign_interrupt` / `verify_interrupt`（HMAC 令牌）+ `build_card`
- `app/mcp/__init__.py`
- `app/mcp/client.py` — `McpClient` + `make_http_transport`（发现 + 调用，含可注入 fake 的接缝）
- `app/mcp/servers/__init__.py`
- `app/mcp/servers/logistics.py` — 物流 MCP Server（`query_logistics`）
- `app/mcp/servers/aftersales.py` — 售后 MCP Server（`query_warranty` / `query_return_progress`）
- `app/api/agent.py` — 转人工坐席端点（接单/接管/回复/结束）
- `app/api/resume.py` — `POST /api/chat/resume`

**修改：**
- `app/models/conversation.py` — `Message` 增 `sender_id` / `sender_name`
- `alembic/versions/0001_initial.py` — `messages` DDL 同步增两列（squash）
- `app/schemas.py` — `MessageOut.sender_name`、`ResumeRequest`
- `app/workflow/graph.py` — 分支改为真实工具 + 引擎 + 卡片；`build_workflow` 去掉静态 `tools`，改由 state 注入
- `app/api/chat.py` — 新增 `get_retriever` / `get_tool_registry`；每请求构建 `ctx` + `executor.agent_tools` 注入；`card` 事件下发
- `app/main.py` — 注册 `agent` / `resume` 路由
- `requirements.txt` — 新增 `mcp`（版本实施时钉定）

**测试：**
- `tests/test_tools_context.py`、`tests/test_tools_registry.py`、`tests/test_tools_executor.py`
- `tests/test_tools_builtin.py`、`tests/test_tools_create_ticket.py`
- `tests/test_mcp_servers.py`、`tests/test_mcp_client.py`
- `tests/test_tools_interrupt.py`、`tests/test_resume_api.py`、`tests/test_agent_api.py`
- `tests/test_workflow_tools.py`；修改 `tests/test_workflow_graph.py`、`tests/test_chat_workflow_api.py`、`tests/test_chat_stream.py`

---

### Task 1: 执行上下文 + 工具注册中心

**Files:**
- Create: `app/tools/__init__.py`, `app/tools/context.py`, `app/tools/registry.py`
- Test: `tests/test_tools_context.py`, `tests/test_tools_registry.py`

**Interfaces:**
- Consumes: P0 `app.models.User`（`.id`/`.role`/`.customer_id`）、`Conversation`（`.id`/`.user_id`）
- Produces:
  - `ExecutionContext(caller_user_id:int, caller_role:str, customer_id:str|None, conversation_id:int, confirmed:bool=False)`
  - `build_execution_context(*, caller:User, owner:User, conversation:Conversation, confirmed:bool=False) -> ExecutionContext` — `customer_id` 取 **会话归属客户**（owner）的 `customer_id`，非 caller 自身（坐席接管时 owner≠caller）
  - `ToolSpec(name, description, input_schema, source, mcp_server=None, requires_customer=False, is_write=False, visible_to_agent=True, ownership_field=None, handler=None)` — `handler` 为 `(args:dict, ctx:ExecutionContext, db:Session) -> str`（仅 builtin）
  - `AgentTool(name, description, run:Callable[[dict],str])`
  - `ToolRegistry`：`.register(spec)`、`.resolve(name)->ToolSpec|None`、`.list_for_agent()->list[ToolSpec]`、`.attach_mcp(client)`、`.call_mcp(server,name,args)->str`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tools_context.py
from app.models import UserRole
from app.models.conversation import Conversation
from app.tools.context import ExecutionContext, build_execution_context


def test_build_context_takes_owner_customer_id_not_caller(user_factory, db_session):
    owner = user_factory(username="cust_1", role=UserRole.customer, customer_id="C0001")
    agent = user_factory(username="agent_1", role=UserRole.agent, customer_id=None)
    conv = Conversation(user_id=owner.id)
    db_session.add(conv); db_session.commit(); db_session.refresh(conv)

    ctx = build_execution_context(caller=agent, owner=owner, conversation=conv, confirmed=True)
    assert ctx.caller_user_id == agent.id
    assert ctx.caller_role == "agent"
    assert ctx.customer_id == "C0001"          # 取 owner 的客户ID，非 caller
    assert ctx.conversation_id == conv.id
    assert ctx.confirmed is True


def test_build_context_default_not_confirmed(user_factory, db_session):
    owner = user_factory(username="cust_2", role=UserRole.customer, customer_id="C0002")
    conv = Conversation(user_id=owner.id)
    db_session.add(conv); db_session.commit(); db_session.refresh(conv)
    ctx = build_execution_context(caller=owner, owner=owner, conversation=conv)
    assert ctx.confirmed is False
```

```python
# tests/test_tools_registry.py
from app.tools.registry import AgentTool, ToolRegistry, ToolSpec


def _spec(name, **kw):
    return ToolSpec(name=name, description=f"{name} desc", input_schema={"type": "object"},
                    source="builtin", **kw)


def test_register_and_resolve():
    reg = ToolRegistry()
    reg.register(_spec("query_order"))
    assert reg.resolve("query_order").name == "query_order"
    assert reg.resolve("nope") is None


def test_register_duplicate_name_overwrites():
    reg = ToolRegistry()
    reg.register(_spec("x", description="first"))
    reg.register(_spec("x", description="second"))
    assert reg.resolve("x").description == "second"


def test_list_for_agent_excludes_invisible():
    reg = ToolRegistry()
    reg.register(_spec("query_order"))
    reg.register(_spec("create_ticket", is_write=True, visible_to_agent=False))
    names = [s.name for s in reg.list_for_agent()]
    assert "query_order" in names and "create_ticket" not in names


def test_list_for_agent_includes_mcp_tools():
    class _FakeMcp:
        def list_tools(self):
            return [ToolSpec(name="query_logistics", description="查物流",
                             input_schema={"type": "object"}, source="mcp", mcp_server="logistics")]

    reg = ToolRegistry()
    reg.register(_spec("query_order"))
    reg.attach_mcp(_FakeMcp())
    names = [s.name for s in reg.list_for_agent()]
    assert set(names) == {"query_order", "query_logistics"}


def test_call_mcp_routes_to_client():
    class _FakeMcp:
        def call_tool(self, server, name, args):
            assert (server, name, args) == ("logistics", "query_logistics", {"order_no": "O1"})
            return "轨迹..."

    reg = ToolRegistry()
    reg.attach_mcp(_FakeMcp())
    assert reg.call_mcp("logistics", "query_logistics", {"order_no": "O1"}) == "轨迹..."
```

- [ ] **Step 2: 运行确认失败** `pytest tests/test_tools_context.py tests/test_tools_registry.py -q` → FAIL（`ModuleNotFoundError: app.tools`）
- [ ] **Step 3: 实现最小代码**

```python
# app/tools/context.py
from dataclasses import dataclass

@dataclass
class ExecutionContext:
    caller_user_id: int
    caller_role: str
    customer_id: str | None
    conversation_id: int
    confirmed: bool = False


def build_execution_context(*, caller, owner, conversation, confirmed: bool = False) -> ExecutionContext:
    return ExecutionContext(
        caller_user_id=caller.id,
        caller_role=caller.role.value,
        customer_id=owner.customer_id,
        conversation_id=conversation.id,
        confirmed=confirmed,
    )
```

```python
# app/tools/registry.py
from dataclasses import dataclass
from typing import Callable

@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    source: str                      # "builtin" | "mcp"
    mcp_server: str | None = None
    requires_customer: bool = False
    is_write: bool = False
    visible_to_agent: bool = True
    ownership_field: str | None = None   # 归属字段名（"order_no"/"item_id"），引擎侧预检用
    handler: Callable | None = None      # builtin: (args, ctx, db) -> str


@dataclass
class AgentTool:
    name: str
    description: str
    run: Callable[[dict], str]


class ToolRegistry:
    def __init__(self):
        self._specs: dict[str, ToolSpec] = {}
        self._mcp = None

    def register(self, spec: ToolSpec) -> None:
        self._specs[spec.name] = spec

    def resolve(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def attach_mcp(self, client) -> None:
        self._mcp = client

    def list_for_agent(self) -> list[ToolSpec]:
        specs = [s for s in self._specs.values() if s.visible_to_agent]
        if self._mcp is not None:
            specs.extend(self._mcp.list_tools())
        return specs

    def call_mcp(self, server: str, name: str, args: dict) -> str:
        if self._mcp is None:
            raise RuntimeError("未接入 MCP 客户端")
        return self._mcp.call_tool(server, name, args)
```

- [ ] **Step 4: 运行确认通过** `pytest tests/test_tools_context.py tests/test_tools_registry.py -q` → PASS
- [ ] **Step 5: 提交** `git add app/tools tests/test_tools_context.py tests/test_tools_registry.py && git commit -m "feat(p4): execution context + tool registry"`

---

### Task 2: 统一工具执行引擎 + 审计 + 归属预检

**Files:**
- Create: `app/tools/executor.py`
- Test: `tests/test_tools_executor.py`

**Interfaces:**
- Consumes: Task 1 `ExecutionContext`/`ToolSpec`/`ToolRegistry`/`AgentTool`；P0 `ToolAuditLog`/`ToolStatus`/`ToolSource`（**`app.models.flywheel`**，不在 `app.models` 命名空间）、`Order`（归属预检）
- Produces: `ToolExecutor(registry:ToolRegistry, db:Session)`：
  - `.execute(name, args, ctx) -> str` — 鉴权→归属预检→执行→审计→回灌观察串；**业务失败返回观察、绝不抛**（`run_agent` 仍走 try/except，观察串让 agent 自适应）
  - `.agent_tools(ctx) -> list[AgentTool]` — 把 `registry.list_for_agent()` 包装成 `run(args)=execute(name,args,ctx)` 的闭包

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tools_executor.py
from datetime import datetime

from app.models import Order
from app.models.flywheel import ToolAuditLog, ToolStatus
from app.tools.context import ExecutionContext
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry, ToolSpec


def _ctx(customer_id="C0001", confirmed=False):
    return ExecutionContext(caller_user_id=1, caller_role="customer",
                            customer_id=customer_id, conversation_id=1, confirmed=confirmed)


def _registry():
    reg = ToolRegistry()
    reg.register(ToolSpec(name="query_product", description="查商品", input_schema={"type": "object"},
                          source="builtin",
                          handler=lambda args, ctx, db: f"商品:{args.get('name')}"))
    reg.register(ToolSpec(name="query_order", description="查订单", input_schema={"type": "object"},
                          source="builtin", requires_customer=True,
                          handler=lambda args, ctx, db: f"订单:{ctx.customer_id}:{args.get('order_no')}"))
    reg.register(ToolSpec(name="create_ticket", description="建工单", input_schema={"type": "object"},
                          source="builtin", is_write=True, visible_to_agent=False,
                          handler=lambda args, ctx, db: "工单已建"))
    return reg


def test_execute_success_returns_observation_and_audits(db_session):
    ex = ToolExecutor(_registry(), db_session)
    out = ex.execute("query_product", {"name": "手机"}, _ctx())
    assert out == "商品:手机"
    log = db_session.query(ToolAuditLog).one()
    assert log.tool_name == "query_product"
    assert log.status == ToolStatus.success
    assert log.tool_source.value == "builtin"


def test_execute_requires_customer_denies_when_no_customer(db_session):
    ex = ToolExecutor(_registry(), db_session)
    out = ex.execute("query_order", {"order_no": "O1"}, _ctx(customer_id=None))
    assert "无权" in out
    assert db_session.query(ToolAuditLog).one().status == ToolStatus.permission_denied


def test_execute_write_requires_confirmed(db_session):
    ex = ToolExecutor(_registry(), db_session)
    out = ex.execute("create_ticket", {"description": "x"}, _ctx(confirmed=False))
    assert "确认" in out
    assert db_session.query(ToolAuditLog).one().status == ToolStatus.validation_blocked


def test_execute_write_allowed_when_confirmed(db_session):
    ex = ToolExecutor(_registry(), db_session)
    out = ex.execute("create_ticket", {"description": "x"}, _ctx(confirmed=True))
    assert out == "工单已建"
    assert db_session.query(ToolAuditLog).one().status == ToolStatus.success


def test_execute_handler_exception_returns_observation_and_audits_failure(db_session):
    reg = ToolRegistry()
    def boom(args, ctx, db): raise ValueError("boom")
    reg.register(ToolSpec(name="bad", description="b", input_schema={"type": "object"},
                          source="builtin", handler=boom))
    ex = ToolExecutor(reg, db_session)
    out = ex.execute("bad", {}, _ctx())
    assert "失败" in out
    assert db_session.query(ToolAuditLog).one().status == ToolStatus.failure


def test_execute_mcp_ownership_field_denies_foreign_order(db_session):
    # 归属预检：order_no 属于 C0002，而 ctx.customer_id 是 C0001 → 拒绝（Review Focus #1）
    db_session.add(Order(customer_id="C0002", order_no="O2", item_id="ITEM2", product_name="x",
                         quantity=1, paid_amount=1, order_status="已签收", after_sale_status="无售后",
                         order_time=datetime(2026, 1, 1)))
    db_session.commit()
    reg = ToolRegistry()
    reg.register(ToolSpec(name="query_logistics", description="查物流", input_schema={"type": "object"},
                          source="mcp", mcp_server="logistics", requires_customer=True,
                          ownership_field="order_no"))
    ex = ToolExecutor(reg, db_session)
    out = ex.execute("query_logistics", {"order_no": "O2"}, _ctx(customer_id="C0001"))
    assert "无权" in out
    assert db_session.query(ToolAuditLog).one().status == ToolStatus.permission_denied


def test_agent_tools_wraps_run_through_executor(db_session):
    ex = ToolExecutor(_registry(), db_session)
    tools = {t.name: t for t in ex.agent_tools(_ctx())}
    assert set(tools) == {"query_product", "query_order"}   # create_ticket 不可见
    assert tools["query_order"].run({"order_no": "O1"}) == "订单:C0001:O1"
    assert db_session.query(ToolAuditLog).count() == 1      # run 走执行器：audit 落库
```

- [ ] **Step 2: 运行确认失败** `pytest tests/test_tools_executor.py -q` → FAIL（`ModuleNotFoundError: app.tools.executor`）
- [ ] **Step 3: 实现最小代码**

```python
# app/tools/executor.py
import logging
from time import monotonic

from app.models import Order
from app.models.flywheel import ToolAuditLog, ToolSource, ToolStatus
from app.tools.registry import AgentTool, ToolRegistry

logger = logging.getLogger(__name__)


def _owns(db, field: str, value, customer_id: str) -> bool:
    """归属预检：订单号/商品项ID 是否属于该 customer_id（§4.5 身份由引擎注入）。"""
    if not value or not customer_id:
        return False
    q = db.query(Order).filter(Order.customer_id == customer_id)
    if field == "order_no":
        q = q.filter(Order.order_no == value)
    elif field == "item_id":
        q = q.filter(Order.item_id == value)
    else:
        return False
    return q.first() is not None


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, db):
        self.registry = registry
        self.db = db

    def _audit(self, spec, args, ctx, status, result=None, error=None, started=None) -> str:
        self.db.add(ToolAuditLog(
            conversation_id=ctx.conversation_id,
            tool_name=spec.name,
            tool_source=ToolSource(spec.source),
            mcp_server=spec.mcp_server,
            arguments=args,
            result_summary=(result[:200] if result else None),
            status=status,
            error_message=(error[:512] if error else None),
            duration_ms=int((monotonic() - started) * 1000) if started is not None else None,
        ))
        self.db.commit()
        return result if result is not None else (error or "")

    def execute(self, name: str, args: dict, ctx) -> str:
        spec = self.registry.resolve(name)
        if spec is None:
            return f"未知工具 {name}"
        args = args or {}
        started = monotonic()
        try:
            if spec.requires_customer and not ctx.customer_id:
                return self._audit(spec, args, ctx, ToolStatus.permission_denied,
                                   error="无权查询该数据", started=started)
            if spec.ownership_field and not _owns(self.db, spec.ownership_field,
                                                  args.get(spec.ownership_field), ctx.customer_id):
                return self._audit(spec, args, ctx, ToolStatus.permission_denied,
                                   error="无权查询该数据", started=started)
            if spec.is_write and not ctx.confirmed:
                return self._audit(spec, args, ctx, ToolStatus.validation_blocked,
                                   error="写操作需用户确认", started=started)
            if spec.source == "builtin":
                result = spec.handler(args, ctx, self.db)
            else:
                result = self.registry.call_mcp(spec.mcp_server, spec.name, args)
            return self._audit(spec, args, ctx, ToolStatus.success, result=result, started=started)
        except Exception as exc:  # 基础设施/处理器异常 → 诚实降级，不裸抛
            logger.warning("工具执行失败 %s：%s", spec.name, exc)
            return self._audit(spec, args, ctx, ToolStatus.failure, error=str(exc), started=started)

    def agent_tools(self, ctx) -> list[AgentTool]:
        return [
            AgentTool(name=s.name, description=s.description,
                      run=lambda args, n=s.name: self.execute(n, args, ctx))
            for s in self.registry.list_for_agent()
        ]
```

- [ ] **Step 4: 运行确认通过** `pytest tests/test_tools_executor.py -q` → PASS
- [ ] **Step 5: 提交** `git add app/tools/executor.py tests/test_tools_executor.py && git commit -m "feat(p4): unified tool executor with audit + ownership precheck"`

---

### Task 3: 内置读工具 query_order / query_product / query_faq

**Files:**
- Create: `app/tools/builtin.py`
- Test: `tests/test_tools_builtin.py`

**Interfaces:**
- Consumes: Task 1 `ToolSpec`；P0 `Order`/`Product` 模型；P2 `Retriever.retrieve(query,top_k)->RetrievalResult`、`build_citations(chunks)->list[Citation]`
- Produces（`app/tools/builtin.py`）：
  - `register_builtin_tools(registry: ToolRegistry, retriever)` — 注册 `query_order`/`query_product`/`query_faq`/`create_ticket`（create_ticket 在 Task 4 增补）
  - `query_order_handler(args, ctx, db) -> str`（按 `ctx.customer_id` 归属过滤；支持 `order_no`/`item_id` 过滤）
  - `query_product_handler(args, ctx, db) -> str`（按 `product_name`/`model` 过滤）
  - `query_faq_handler(args, ctx, retriever) -> str`（`args["query"]` → `retriever.retrieve`，闸不过返回 `passed=False`；返回 JSON 串含证据编号+片段）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tools_builtin.py
import json
from datetime import datetime

from app.models import Order, Product
from app.rag.retrieval import RetrievalResult, ScoredChunk
from app.tools.builtin import (query_faq_handler, query_order_handler,
                               query_product_handler, register_builtin_tools)
from app.tools.context import ExecutionContext
from app.tools.registry import ToolRegistry

CTX = ExecutionContext(caller_user_id=1, caller_role="customer",
                       customer_id="C0001", conversation_id=1)


def _seed_order(db, customer_id="C0001", order_no="O1", item_id="ITEM1", name="手机"):
    db.add(Order(customer_id=customer_id, order_no=order_no, item_id=item_id,
                 product_name=name, quantity=1, paid_amount=1999, order_status="已签收",
                 after_sale_status="无售后", order_time=datetime(2026, 10, 1)))
    db.commit()


def test_query_order_returns_only_own_orders(db_session):
    _seed_order(db_session, customer_id="C0001", order_no="O1")
    _seed_order(db_session, customer_id="C0002", order_no="O2", item_id="ITEM2")
    out = json.loads(query_order_handler({}, CTX, db_session))
    assert [o["order_no"] for o in out["orders"]] == ["O1"]      # 越权订单被过滤


def test_query_order_filters_by_order_no(db_session):
    _seed_order(db_session, order_no="O1")
    _seed_order(db_session, order_no="O9", item_id="ITEM9")
    out = json.loads(query_order_handler({"order_no": "O1"}, CTX, db_session))
    assert [o["order_no"] for o in out["orders"]] == ["O1"]


def test_query_product_by_name_and_model(db_session):
    db_session.add(Product(product_name="手机A", model="M1", order_spec="128G",
                           product_type="数码", seven_day_return="支持", warranty="12个月"))
    db_session.commit()
    out = json.loads(query_product_handler({"product_name": "手机A"}, CTX, db_session))
    assert out["products"][0]["model"] == "M1"
    out2 = json.loads(query_product_handler({"model": "M1"}, CTX, db_session))
    assert out2["products"][0]["warranty"] == "12个月"


class _Rag:
    def retrieve(self, query, top_k=10):
        return RetrievalResult(
            chunks=[ScoredChunk(chunk_id=1, score=0.9, category="政策",
                                section_path="政策 > R01", content_type="policy",
                                snippet="七天无理由退货")],
            evidence_confidence=0.9, passed=True)


def test_query_faq_returns_numbered_evidence():
    out = json.loads(query_faq_handler({"query": "退货政策"}, CTX, retriever=_Rag()))
    assert out["passed"] is True
    assert out["evidence"][0]["n"] == 1
    assert "七天无理由退货" in out["evidence"][0]["snippet"]


def test_query_faq_gate_fail_returns_honest():
    class _RagFail:
        def retrieve(self, query, top_k=10):
            return RetrievalResult(chunks=[], evidence_confidence=0.1, passed=False)
    out = json.loads(query_faq_handler({"query": "x"}, CTX, retriever=_RagFail()))
    assert out["passed"] is False and out["evidence"] == []


def test_register_builtin_tools_registers_read_tools():
    reg = ToolRegistry()
    register_builtin_tools(reg, retriever=_Rag())
    names = {s.name for s in reg.list_for_agent()}
    assert names == {"query_order", "query_product", "query_faq"}
    assert reg.resolve("query_order").requires_customer is True
```

- [ ] **Step 2: 运行确认失败** `pytest tests/test_tools_builtin.py -q` → FAIL
- [ ] **Step 3: 实现最小代码**

```python
# app/tools/builtin.py
import json
from datetime import datetime

from app.models import Order, Product
from app.tools.registry import ToolSpec


def _d(v):
    return v.isoformat() if isinstance(v, datetime) else v


def query_order_handler(args, ctx, db) -> str:
    q = db.query(Order).filter(Order.customer_id == ctx.customer_id)
    if args.get("order_no"):
        q = q.filter(Order.order_no == args["order_no"])
    if args.get("item_id"):
        q = q.filter(Order.item_id == args["item_id"])
    rows = q.all()
    return json.dumps({"orders": [
        {"order_no": o.order_no, "item_id": o.item_id, "product_name": o.product_name,
         "model_spec": o.model_spec, "quantity": o.quantity, "paid_amount": str(o.paid_amount),
         "order_status": o.order_status, "after_sale_status": o.after_sale_status,
         "order_time": _d(o.order_time), "sign_time": _d(o.sign_time)}
        for o in rows
    ]}, ensure_ascii=False)


def query_product_handler(args, ctx, db) -> str:
    q = db.query(Product)
    if args.get("product_name"):
        q = q.filter(Product.product_name.like(f"%{args['product_name']}%"))
    if args.get("model"):
        q = q.filter(Product.model == args["model"])
    rows = q.all()
    return json.dumps({"products": [
        {"product_name": p.product_name, "model": p.model, "order_spec": p.order_spec,
         "product_type": p.product_type, "seven_day_return": p.seven_day_return,
         "warranty": p.warranty}
        for p in rows
    ]}, ensure_ascii=False)


def query_faq_handler(args, ctx, retriever) -> str:
    r = retriever.retrieve(args.get("query", ""))
    if not r.passed:
        return json.dumps({"passed": False, "evidence": []}, ensure_ascii=False)
    evidence = [{"n": i, "section_path": c.section_path, "snippet": c.snippet}
                for i, c in enumerate(r.chunks, start=1)]
    return json.dumps({"passed": True, "evidence": evidence}, ensure_ascii=False)


def register_builtin_tools(registry, retriever) -> None:
    registry.register(ToolSpec(
        name="query_order", description="查询当前客户自己的订单（可按订单号/商品项ID过滤）",
        input_schema={"type": "object", "properties": {"order_no": {"type": "string"},
                        "item_id": {"type": "string"}}},
        source="builtin", requires_customer=True, handler=query_order_handler))
    registry.register(ToolSpec(
        name="query_product", description="查询商品信息（按名称/型号）",
        input_schema={"type": "object", "properties": {"product_name": {"type": "string"},
                        "model": {"type": "string"}}},
        source="builtin", handler=query_product_handler))
    registry.register(ToolSpec(
        name="query_faq", description="检索知识库（政策/售后手册/商品规格）回答问题",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}},
                      "required": ["query"]},
        source="builtin",
        handler=lambda args, ctx, db: query_faq_handler(args, ctx, retriever)))
```

> 注：builtin 处理器统一 3 参 `(args, ctx, db)`，执行器（Task 2）把请求 `Session` 作为 `db` 传入；本任务测试直接调 handler 函数、传 `db_session` fixture，不依赖执行器。

- [ ] **Step 4: 运行确认通过** `pytest tests/test_tools_builtin.py -q` → PASS
- [ ] **Step 5: 提交** `git add app/tools/builtin.py tests/test_tools_builtin.py && git commit -m "feat(p4): builtin read tools query_order/query_product/query_faq"`

---

### Task 4: 内置写工具 create_ticket（幂等）

**Files:**
- Modify: `app/tools/builtin.py`
- Test: `tests/test_tools_create_ticket.py`

**Interfaces:**
- Consumes: Task 1 `ToolSpec`；P0 `Ticket` 模型（`ticket_no` String(32) PK / `idempotency_key` String(64) UNIQUE NOT NULL / `conversation_id` BigInteger NOT NULL / `status` default "open"）
- Produces: `create_ticket_handler(args, ctx, db) -> str`；在 `register_builtin_tools` 中注册为 `is_write=True, visible_to_agent=False`；幂等：`args["idempotency_key"]` 命中已存在工单时返回既有工单号，不重复建

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tools_create_ticket.py
import json

from app.models import Ticket
from app.tools.builtin import create_ticket_handler
from app.tools.context import ExecutionContext

CTX = ExecutionContext(caller_user_id=1, caller_role="customer",
                       customer_id="C0001", conversation_id=7, confirmed=True)


def test_create_ticket_writes_one_ticket(db_session):
    out = json.loads(create_ticket_handler(
        {"description": "物流丢失", "type": "投诉", "idempotency_key": "K1"}, CTX, db_session))
    ticket = db_session.query(Ticket).one()
    assert ticket.ticket_no == out["ticket_no"]
    assert ticket.conversation_id == 7
    assert ticket.status == "open"
    assert ticket.idempotency_key == "K1"


def test_create_ticket_is_idempotent(db_session):
    a = create_ticket_handler({"description": "x", "type": "投诉", "idempotency_key": "K1"}, CTX, db_session)
    b = create_ticket_handler({"description": "x", "type": "投诉", "idempotency_key": "K1"}, CTX, db_session)
    assert json.loads(a)["ticket_no"] == json.loads(b)["ticket_no"]
    assert db_session.query(Ticket).count() == 1        # 只落一张
```

- [ ] **Step 2: 运行确认失败** `pytest tests/test_tools_create_ticket.py -q` → FAIL（`create_ticket_handler` 未定义）
- [ ] **Step 3: 实现最小代码**

```python
# app/tools/builtin.py 追加
import hashlib
import secrets
import time


def _gen_ticket_no(conversation_id: int) -> str:
    # 毫秒时间戳 + 随机后缀，避免同秒多单撞 PK（ticket_no 是主键）
    return f"TK{conversation_id % 100000:05d}{int(time.time() * 1000) % 10000000:07d}{secrets.randbelow(100):02d}"


def create_ticket_handler(args, ctx, db) -> str:
    idem = args.get("idempotency_key")
    existing = db.query(Ticket).filter(Ticket.idempotency_key == idem).first() if idem else None
    if existing is not None:
        return json.dumps({"ticket_no": existing.ticket_no, "duplicate": True}, ensure_ascii=False)
    ticket = Ticket(
        ticket_no=_gen_ticket_no(ctx.conversation_id),
        conversation_id=ctx.conversation_id,
        description=args.get("description", ""),
        type=args.get("type", "投诉"),
        status="open",
        idempotency_key=idem or hashlib.sha256(
            f"{ctx.conversation_id}:{args.get('description','')}".encode()).hexdigest(),
    )
    db.add(ticket); db.commit()
    return json.dumps({"ticket_no": ticket.ticket_no, "duplicate": False}, ensure_ascii=False)
```

并在 `register_builtin_tools` 末尾注册：

```python
    registry.register(ToolSpec(
        name="create_ticket", description="创建人工工单（需用户确认）",
        input_schema={"type": "object",
                      "properties": {"description": {"type": "string"},
                                     "type": {"type": "string"},
                                     "idempotency_key": {"type": "string"}},
                      "required": ["description"]},
        source="builtin", is_write=True, visible_to_agent=False,
        handler=create_ticket_handler))
```

- [ ] **Step 4: 运行确认通过** `pytest tests/test_tools_create_ticket.py -q` → PASS
- [ ] **Step 5: 提交** `git add app/tools/builtin.py tests/test_tools_create_ticket.py && git commit -m "feat(p4): idempotent create_ticket write tool"`

---

### Task 5: 两个 MCP Server（物流 / 售后）

**Files:**
- Create: `app/mcp/__init__.py`, `app/mcp/servers/__init__.py`, `app/mcp/servers/logistics.py`, `app/mcp/servers/aftersales.py`
- Modify: `requirements.txt`（新增 `mcp`，版本经 PyPI JSON 核实后钉定）
- Test: `tests/test_mcp_servers.py`

**Interfaces:**
- Consumes: P0 `Logistics`/`Order`/`Product` 模型
- Produces（纯函数，独立于 MCP 传输，直接单测）：
  - `app/mcp/servers/logistics.py::query_logistics_fn(db, order_no) -> str`（`Logistics` 表，`is_latest=True` 优先）
  - `app/mcp/servers/aftersales.py::query_warranty_fn(db, item_id) -> str`（由 `item_id` → `Order` → 签收时间 + `Product.warranty` 判定是否在保）
  - `app/mcp/servers/aftersales.py::query_return_progress_fn(db, order_no) -> str`（`Logistics.logistics_type='退货'` 最新记录）
  - 每个 `server.py` 另有 `build_mcp_server()` + `if __name__ == "__main__": build_mcp_server().run()` 薄封装

- [ ] **Step 1: 写失败测试**

```python
# tests/test_mcp_servers.py
import json
from datetime import datetime

from app.models import Logistics, Order, Product
from app.mcp.servers.logistics import query_logistics_fn
from app.mcp.servers.aftersales import query_warranty_fn, query_return_progress_fn


def test_query_logistics_prefers_latest(db_session):
    db_session.add_all([
        Logistics(order_no="O1", item_ids="ITEM1", waybill_no="W1", logistics_type="正向",
                  carrier="顺丰", status="已签收", latest_time=datetime(2026, 10, 1),
                  is_latest=False, trajectory="旧轨迹"),
        Logistics(order_no="O1", item_ids="ITEM1", waybill_no="W2", logistics_type="正向",
                  carrier="顺丰", status="运输中", latest_time=datetime(2026, 10, 2),
                  is_latest=True, trajectory="新轨迹"),
    ])
    db_session.commit()
    out = json.loads(query_logistics_fn(db_session, "O1"))
    assert out["status"] == "运输中"
    assert out["trajectory"] == "新轨迹"


def test_query_warranty_in_warranty(db_session):
    db_session.add(Product(product_name="手机", model="M1", order_spec="128G",
                           product_type="数码", seven_day_return="支持", warranty="12个月"))
    db_session.add(Order(customer_id="C1", order_no="O1", item_id="ITEM1", product_name="手机",
                         model_spec="M1", quantity=1, paid_amount=1999, order_status="已签收",
                         after_sale_status="无售后", order_time=datetime(2026, 1, 1),
                         sign_time=datetime(2026, 10, 1)))
    db_session.commit()
    out = json.loads(query_warranty_fn(db_session, "ITEM1"))
    assert out["warranty"] == "12个月"
    assert out["in_warranty"] is True


def test_query_return_progress(db_session):
    db_session.add(Logistics(order_no="O1", item_ids="ITEM1", waybill_no="R1", logistics_type="退货",
                             carrier="圆通", status="已签收", latest_time=datetime(2026, 10, 3),
                             is_latest=True, trajectory="退货已签收"))
    db_session.commit()
    out = json.loads(query_return_progress_fn(db_session, "O1"))
    assert out["status"] == "已签收"
```

- [ ] **Step 2: 运行确认失败** `pytest tests/test_mcp_servers.py -q` → FAIL
- [ ] **Step 3: 实现最小代码**

```python
# app/mcp/servers/logistics.py
import json

from app.models import Logistics


def query_logistics_fn(db, order_no: str) -> str:
    rows = (db.query(Logistics).filter(Logistics.order_no == order_no)
            .order_by(Logistics.is_latest.desc(), Logistics.latest_time.desc()).all())
    if not rows:
        return json.dumps({"found": False}, ensure_ascii=False)
    r = rows[0]
    return json.dumps({"found": True, "order_no": r.order_no, "waybill_no": r.waybill_no,
                       "logistics_type": r.logistics_type, "carrier": r.carrier,
                       "status": r.status, "latest_time": r.latest_time.isoformat(),
                       "trajectory": r.trajectory}, ensure_ascii=False)


def build_mcp_server():
    from mcp.server.fastmcp import FastMCP  # 见 dev-notes/ch08.md 核实
    mcp = FastMCP("sayhelp-logistics")

    @mcp.tool()
    def query_logistics(order_no: str) -> str:
        from app.db import SessionLocal
        with SessionLocal() as db:
            return query_logistics_fn(db, order_no)

    return mcp


if __name__ == "__main__":
    build_mcp_server().run()
```

```python
# app/mcp/servers/aftersales.py
import json
from datetime import datetime

from app.models import Logistics, Order, Product


def _months(s: str) -> int:
    digits = "".join(ch for ch in s if ch.isdigit())
    return int(digits) if digits else 0


def query_warranty_fn(db, item_id: str) -> str:
    order = db.query(Order).filter(Order.item_id == item_id).first()
    if order is None:
        return json.dumps({"found": False}, ensure_ascii=False)
    product = None
    if order.model_spec:
        product = db.query(Product).filter(Product.model == order.model_spec).first()
    if product is None:
        product = db.query(Product).filter(Product.product_name == order.product_name).first()
    warranty = product.warranty if product else "未知"
    in_warranty = False
    if order.sign_time is not None and warranty not in (None, "", "未知"):
        in_warranty = (datetime.now() - order.sign_time).days <= _months(warranty) * 30
    return json.dumps({"found": True, "item_id": item_id, "warranty": warranty,
                       "sign_time": order.sign_time.isoformat() if order.sign_time else None,
                       "in_warranty": in_warranty}, ensure_ascii=False)


def query_return_progress_fn(db, order_no: str) -> str:
    r = (db.query(Logistics)
         .filter(Logistics.order_no == order_no, Logistics.logistics_type == "退货")
         .order_by(Logistics.latest_time.desc()).first())
    if r is None:
        return json.dumps({"found": False}, ensure_ascii=False)
    return json.dumps({"found": True, "order_no": r.order_no, "waybill_no": r.waybill_no,
                       "status": r.status, "latest_time": r.latest_time.isoformat(),
                       "trajectory": r.trajectory}, ensure_ascii=False)


def build_mcp_server():
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("sayhelp-aftersales")

    @mcp.tool()
    def query_warranty(item_id: str) -> str:
        from app.db import SessionLocal
        with SessionLocal() as db:
            return query_warranty_fn(db, item_id)

    @mcp.tool()
    def query_return_progress(order_no: str) -> str:
        from app.db import SessionLocal
        with SessionLocal() as db:
            return query_return_progress_fn(db, order_no)

    return mcp


if __name__ == "__main__":
    build_mcp_server().run()
```

- [ ] **Step 3b: 核实 `mcp` SDK 接口**：`pip install "mcp>=1.0,<2"`（版本经 `https://pypi.org/pypi/mcp/json` 核实），introspect 已装包确认 `mcp.server.fastmcp.FastMCP`、`@mcp.tool()`、`.run()` 存在且签名如上；把结论与版本写入 `dev-notes/ch08.md`。若 `FastMCP` 名/签名不符，改薄封装层并在 ch08 记录，**不得伪造**。
- [ ] **Step 4: 运行确认通过** `pytest tests/test_mcp_servers.py -q` → PASS（仅测纯函数，不 import `mcp`）
- [ ] **Step 5: 提交** `git add app/mcp requirements.txt tests/test_mcp_servers.py && git commit -m "feat(p4): logistics + after-sales MCP servers"`

---

### Task 6: MCP 客户端 + 动态发现 + 注册中心集成

**Files:**
- Create: `app/mcp/client.py`
- Test: `tests/test_mcp_client.py`

**Interfaces:**
- Consumes: Task 1 `ToolSpec`/`ToolRegistry`
- Produces: `McpClient(transport)`：
  - `.list_tools() -> list[ToolSpec]` — 每请求动态发现（source="mcp"、mcp_server 标注、`ownership_field` 标注）
  - `.call_tool(server, name, args) -> str`
  - `.refresh()` — 清空缓存、重新发现（Server 重启后重新发现，客服服务不重启）
  - `make_http_transport()` — 真实 MCP streamable HTTP 客户端传输（惰性连接，Task 10 接线用；SDK 签名在 ch08 核实）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_mcp_client.py
from app.mcp.client import McpClient


class _FakeTransport:
    """模拟 MCP 传输：list_tools / call_tool。"""
    def __init__(self, tools=None):
        self.tools = tools or [
            {"name": "query_logistics", "description": "查物流",
             "inputSchema": {"type": "object"}, "server": "logistics"},
        ]
        self.calls = []

    def list_tools(self):
        return self.tools

    def call_tool(self, server, name, args):
        self.calls.append((server, name, args))
        return f"result:{name}"


def test_discover_returns_mcp_toolspecs_with_ownership():
    client = McpClient(_FakeTransport())
    tools = client.list_tools()
    t = tools[0]
    assert t.name == "query_logistics"
    assert t.source == "mcp" and t.mcp_server == "logistics"
    assert t.ownership_field == "order_no"      # 引擎侧归属预检字段
    assert t.requires_customer is True


def test_call_tool_routes_to_transport():
    tp = _FakeTransport()
    client = McpClient(tp)
    out = client.call_tool("logistics", "query_logistics", {"order_no": "O1"})
    assert out == "result:query_logistics"
    assert tp.calls == [("logistics", "query_logistics", {"order_no": "O1"})]


def test_refresh_rediscovers():
    tp = _FakeTransport()
    client = McpClient(tp)
    assert len(client.list_tools()) == 1
    tp.tools.append({"name": "query_warranty", "description": "查保修",
                     "inputSchema": {"type": "object"}, "server": "aftersales"})
    client.refresh()
    assert {t.name for t in client.list_tools()} == {"query_logistics", "query_warranty"}
```

- [ ] **Step 2: 运行确认失败** `pytest tests/test_mcp_client.py -q` → FAIL
- [ ] **Step 3: 实现最小代码**

```python
# app/mcp/client.py
from app.tools.registry import ToolSpec

# 每个 MCP 工具的归属字段（引擎侧预检用，§4.5 身份由引擎注入）。
_OWNERSHIP_FIELD = {
    ("logistics", "query_logistics"): "order_no",
    ("aftersales", "query_warranty"): "item_id",
    ("aftersales", "query_return_progress"): "order_no",
}


class McpClient:
    """MCP 客户端：动态发现工具、调用工具；transport 可注入以便测试。

    真实 transport 用 `mcp` SDK 的 streamable HTTP 客户端（见 dev-notes/ch08.md）；
    本类只依赖 transport 的 list_tools()/call_tool() 协议，SDK 差异被隔离在 transport 里。
    """

    def __init__(self, transport):
        self._transport = transport
        self._cache: list[ToolSpec] | None = None

    def list_tools(self) -> list[ToolSpec]:
        if self._cache is None:
            self._cache = self._discover()
        return self._cache

    def _discover(self) -> list[ToolSpec]:
        specs = []
        for raw in self._transport.list_tools():
            server = raw.get("server") or raw["name"]
            name = raw["name"]
            specs.append(ToolSpec(
                name=name, description=raw["description"],
                input_schema=raw.get("inputSchema") or {"type": "object"},
                source="mcp", mcp_server=server,
                requires_customer=True,
                ownership_field=_OWNERSHIP_FIELD.get((server, name)),
            ))
        return specs

    def call_tool(self, server: str, name: str, args: dict) -> str:
        return self._transport.call_tool(server, name, args)

    def refresh(self) -> None:
        self._cache = None


def make_http_transport():
    """返回真实 MCP streamable HTTP 客户端传输（惰性：不建立连接，首次 list_tools 才连）。

    mcp SDK 精确签名在实施时经 dev-notes/ch08.md 核实；本函数是唯一触真实 SDK 的接缝，
    测试不触它（fixture 覆盖 get_tool_registry）。核实后据此实现，不得伪造接口。
    """
    from mcp.client.streamable_http import streamable_http_client  # 待 ch08 核实
    raise NotImplementedError("make_http_transport 须按 dev-notes/ch08.md 核实的 SDK 签名实现")
```

- [ ] **Step 4: 运行确认通过** `pytest tests/test_mcp_client.py -q` → PASS
- [ ] **Step 5: 提交** `git add app/mcp/client.py tests/test_mcp_client.py && git commit -m "feat(p4): MCP client with dynamic discovery + ownership"`

> 注：`make_http_transport()` 的真实 SDK 实现不在本任务测试范围内（测试用 fake transport），留待 Task 6/10 的 Step 3b 经 ch08 核实后落地。若实现者已按 ch08 核实并落地，则删除 `raise NotImplementedError`。

---

### Task 7: interrupt 令牌 + 卡片契约

**Files:**
- Create: `app/tools/interrupt.py`
- Test: `tests/test_tools_interrupt.py`

**Interfaces:**
- Consumes: `app.config.settings.jwt_secret`（已存在）
- Produces:
  - `sign_interrupt(conversation_id:int, card_type:str, *, ttl_s:int=1800) -> tuple[str, str]` — 返回 `(interrupt_id 令牌, nonce)`
  - `verify_interrupt(token:str, conversation_id:int, card_type:str) -> dict | None` — 验签 + 过期 + 绑定，通过返回 payload（含 `nonce`），失败返回 `None`
  - `build_card(card_type, interrupt_id, payload) -> dict` — SSE `card` 事件 data 形状
  - `CARD_TYPES = {"order_select", "ticket_confirm", "transfer_human", "refund_preview"}`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tools_interrupt.py
from app.tools.interrupt import (
    build_card, sign_interrupt, verify_interrupt, CARD_TYPES,
)


def test_sign_and_verify_roundtrip():
    token, nonce = sign_interrupt(conv_id=7, card_type="ticket_confirm")
    payload = verify_interrupt(token, conversation_id=7, card_type="ticket_confirm")
    assert payload is not None
    assert payload["conversation_id"] == 7
    assert payload["card_type"] == "ticket_confirm"
    assert payload["nonce"] == nonce


def test_verify_rejects_wrong_conversation():
    token, _ = sign_interrupt(7, "transfer_human")
    assert verify_interrupt(token, conversation_id=8, card_type="transfer_human") is None  # 防跨会话


def test_verify_rejects_wrong_card_type():
    token, _ = sign_interrupt(7, "order_select")
    assert verify_interrupt(token, conversation_id=7, card_type="ticket_confirm") is None


def test_verify_rejects_tampered():
    token, _ = sign_interrupt(7, "ticket_confirm")
    assert verify_interrupt(token + "x", conversation_id=7, card_type="ticket_confirm") is None


def test_build_card_shape():
    card = build_card("ticket_confirm", "tok", {"description": "物流慢"})
    assert card == {"type": "ticket_confirm", "interrupt_id": "tok", "payload": {"description": "物流慢"}}


def test_card_types_cover_four():
    assert CARD_TYPES == {"order_select", "ticket_confirm", "transfer_human", "refund_preview"}
```

- [ ] **Step 2: 运行确认失败** `pytest tests/test_tools_interrupt.py -q` → FAIL
- [ ] **Step 3: 实现最小代码**

```python
# app/tools/interrupt.py
import base64
import hashlib
import hmac
import json
import secrets
import time

from app.config import settings

CARD_TYPES = {"order_select", "ticket_confirm", "transfer_human", "refund_preview"}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(msg: str) -> str:
    return _b64(hmac.new(settings.jwt_secret.encode(), msg.encode(), hashlib.sha256).digest())


def sign_interrupt(conversation_id: int, card_type: str, *, ttl_s: int = 1800) -> tuple[str, str]:
    nonce = secrets.token_urlsafe(16)
    payload = {"conversation_id": conversation_id, "card_type": card_type,
               "nonce": nonce, "exp": int(time.time()) + ttl_s}
    body = _b64(json.dumps(payload, ensure_ascii=False).encode())
    return f"{body}.{_sign(body)}", nonce


def verify_interrupt(token: str, conversation_id: int, card_type: str) -> dict | None:
    try:
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(body)):
            return None
        payload = json.loads(_b64d(body))
    except Exception:
        return None
    if payload.get("conversation_id") != conversation_id:
        return None
    if payload.get("card_type") != card_type:
        return None
    if payload.get("exp", 0) < int(time.time()):
        return None
    return payload


def build_card(card_type: str, interrupt_id: str, payload: dict) -> dict:
    return {"type": card_type, "interrupt_id": interrupt_id, "payload": payload}
```

- [ ] **Step 4: 运行确认通过** `pytest tests/test_tools_interrupt.py -q` → PASS
- [ ] **Step 5: 提交** `git add app/tools/interrupt.py tests/test_tools_interrupt.py && git commit -m "feat(p4): signed interrupt tokens + card contract"`

---

### Task 8: 转人工真实工作台（状态机 + 坐席端点 + 身份如实标注）

**Files:**
- Modify: `app/models/conversation.py`（`Message` 增 `sender_id`/`sender_name`）、`alembic/versions/0001_initial.py`（messages DDL 增两列）、`app/schemas.py`（`MessageOut.sender_name`）
- Create: `app/api/agent.py`
- Test: `tests/test_agent_api.py`

**Interfaces:**
- Consumes: P0 `User`/`UserRole`、`Conversation`（status 状态机）、`Message`；`app.auth.deps.get_current_user`/`require_role`；`app.api.conversations`（不需要 `get_owned_conversation`，坐席跨用户）
- Produces（`app/api/agent.py`，`prefix="/api/agent"`，全部 `require_role("agent","admin")`）：
  - `GET /conversations?status=agent_waiting` — 待接入会话列表
  - `POST /conversations/{id}/claim` — 坐席接单：`status` `agent_waiting → agent_connected`
  - `POST /conversations/{id}/messages` — 坐席回复：落 `Message(role=assistant, sender_id=user.id, sender_name=user.display_name)`
  - `POST /conversations/{id}/close` — 结束：`status → ended`
- 状态机取值（spec §3.3）：`open` / `agent_waiting` / `agent_connected` / `ended`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_agent_api.py
from app.models import Conversation, Message, UserRole
from app.schemas import MessageOut


def _auth(client, username="agent"):
    token = client.post("/api/auth/login",
                        data={"username": username, "password": "SayHelp123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_agent_claims_and_replies_with_sender_name(client, user_factory, db_session):
    customer = user_factory(username="cust_x", role=UserRole.customer, customer_id="C0001")
    agent = user_factory(username="agent_x", role=UserRole.agent, display_name="坐席 王小明")
    conv = Conversation(user_id=customer.id, status="agent_waiting")
    db_session.add(conv); db_session.commit(); db_session.refresh(conv)

    h = _auth(client, "agent_x")
    r = client.get("/api/agent/conversations", params={"status": "agent_waiting"}, headers=h)
    assert r.status_code == 200
    assert any(c["id"] == conv.id for c in r.json())

    r = client.post(f"/api/agent/conversations/{conv.id}/claim", headers=h)
    assert r.status_code == 200
    db_session.refresh(conv)
    assert conv.status == "agent_connected"

    r = client.post(f"/api/agent/conversations/{conv.id}/messages",
                    json={"content": "您好，我是坐席"}, headers=h)
    assert r.status_code == 200
    body = MessageOut.model_validate(r.json())
    assert body.sender_name == "坐席 王小明"
    msg = db_session.query(Message).filter(Message.conversation_id == conv.id).one()
    assert msg.sender_id == agent.id
    assert msg.role.value == "assistant"


def test_customer_cannot_access_agent_endpoints(client, user_factory, db_session):
    customer = user_factory(username="cust_y", role=UserRole.customer, customer_id="C0002")
    conv = Conversation(user_id=customer.id)
    db_session.add(conv); db_session.commit(); db_session.refresh(conv)
    h = _auth(client, "cust_y")
    assert client.post(f"/api/agent/conversations/{conv.id}/claim", headers=h).status_code == 403
```

- [ ] **Step 2: 运行确认失败** `pytest tests/test_agent_api.py -q` → FAIL
- [ ] **Step 3: 实现最小代码**

模型（`app/models/conversation.py` `Message` 类内，`created_at` 之后追加；`BigInteger`/`String` 已在该文件顶部 import）：

```python
    sender_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

迁移（`alembic/versions/0001_initial.py`，messages DDL 字符串）：在 `created_at DATETIME NOT NULL DEFAULT now(), ` 之后、`PRIMARY KEY (id)` 之前插入两行，最终 messages DDL 为：

```
id BIGINT NOT NULL AUTO_INCREMENT, 
conversation_id BIGINT NOT NULL, 
`role` ENUM('user','assistant','tool','system') NOT NULL, 
content TEXT NOT NULL, 
tool_call_id VARCHAR(64), 
tool_calls JSON, 
citations JSON, 
feedback JSON, 
created_at DATETIME NOT NULL DEFAULT now(), 
sender_id BIGINT, 
sender_name VARCHAR(64), 
PRIMARY KEY (id)
```

（改完跑 `pytest tests/test_migration_parity.py -q` 确认模型↔迁移一致。）

`app/schemas.py` `MessageOut` 追加字段：

```python
    sender_name: str | None
```

`app/api/agent.py`：

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import require_role
from app.db import get_db
from app.models import Conversation, Message, User
from app.schemas import ConversationOut, MessageOut

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/conversations", response_model=list[ConversationOut])
def list_waiting(status_filter: str = "agent_waiting", db: Session = Depends(get_db),
                 user: User = Depends(require_role("agent", "admin"))):
    rows = (db.query(Conversation).filter(Conversation.status == status_filter)
            .order_by(Conversation.updated_at.desc()).all())
    return [ConversationOut.model_validate(r) for r in rows]


@router.post("/conversations/{conv_id}/claim", response_model=ConversationOut)
def claim(conv_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("agent", "admin"))):
    conv = db.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    if conv.status != "agent_waiting":
        raise HTTPException(status.HTTP_409_CONFLICT, "会话不在待接入状态")
    conv.status = "agent_connected"
    db.commit(); db.refresh(conv)
    return ConversationOut.model_validate(conv)


@router.post("/conversations/{conv_id}/messages", response_model=MessageOut)
def agent_reply(conv_id: int, body: dict, db: Session = Depends(get_db),
                user: User = Depends(require_role("agent", "admin"))):
    conv = db.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    msg = Message(conversation_id=conv.id, role="assistant", content=body.get("content", ""),
                  sender_id=user.id, sender_name=user.display_name)
    db.add(msg)
    conv.updated_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(msg)
    return MessageOut.model_validate(msg)


@router.post("/conversations/{conv_id}/close", response_model=ConversationOut)
def close(conv_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("agent", "admin"))):
    conv = db.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    conv.status = "ended"
    db.commit(); db.refresh(conv)
    return ConversationOut.model_validate(conv)
```

- [ ] **Step 4: 运行确认通过** `pytest tests/test_agent_api.py tests/test_migration_parity.py -q` → PASS
- [ ] **Step 5: 提交** `git add app/models/conversation.py alembic/versions/0001_initial.py app/schemas.py app/api/agent.py tests/test_agent_api.py && git commit -m "feat(p4): human handoff workstation with honest agent identity"`

---

### Task 9: resume 端点（转人工 / 确认建工单 / 订单选择 / 取消）

**Files:**
- Create: `app/api/resume.py`
- Modify: `app/schemas.py`（`ResumeRequest`）
- Test: `tests/test_resume_api.py`

**Interfaces:**
- Consumes: Task 7 `verify_interrupt`/`sign_interrupt`/`build_card`；Task 4 `create_ticket_handler`；Task 1 `ExecutionContext`；`app.api.conversations.get_owned_conversation`（签名 `(conv_id, user, db)`）；`app.auth.deps.get_current_user`
- Produces: `POST /api/chat/resume`（`ResumeRequest{conversation_id, interrupt_id, action, payload}`；返回 JSON）：
  - `action="transfer"`（card_type=`transfer_human`）→ `conversation.status = agent_waiting`
  - `action="confirm_ticket"`（card_type=`ticket_confirm`）→ `create_ticket`（幂等 key 由令牌 nonce 派生）
  - `action="select_order"`（card_type=`order_select`）→ 返回 `refund_preview` 卡片（不真实提交退款）
  - `action="cancel"` → 返回「已取消」

- [ ] **Step 1: 写失败测试**

```python
# tests/test_resume_api.py
import json

from app.models import Ticket
from app.tools.interrupt import sign_interrupt


def _auth(client, username="user_a"):
    token = client.post("/api/auth/login",
                        data={"username": username, "password": "SayHelp123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_transfer_sets_agent_waiting(client, user_a, conv_a, db_session):
    token, _ = sign_interrupt(conv_a.id, "transfer_human")
    r = client.post("/api/chat/resume", json={
        "conversation_id": conv_a.id, "interrupt_id": token,
        "action": "transfer", "payload": {}}, headers=_auth(client, "user_a"))
    assert r.status_code == 200
    db_session.refresh(conv_a)
    assert conv_a.status == "agent_waiting"


def test_confirm_ticket_idempotent(client, user_a, conv_a, db_session):
    h = _auth(client, "user_a")
    token, _ = sign_interrupt(conv_a.id, "ticket_confirm")
    body = {"conversation_id": conv_a.id, "interrupt_id": token,
            "action": "confirm_ticket", "payload": {"description": "物流慢", "type": "投诉"}}
    r1 = client.post("/api/chat/resume", json=body, headers=h)
    r2 = client.post("/api/chat/resume", json=body, headers=h)   # 双击重放
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["ticket_no"] == r2.json()["ticket_no"]
    assert db_session.query(Ticket).count() == 1                 # 幂等只落一张


def test_resume_rejects_cross_session(client, user_a, user_b, conv_a, conv_b):
    token, _ = sign_interrupt(conv_a.id, "transfer_human")
    r = client.post("/api/chat/resume", json={
        "conversation_id": conv_b.id, "interrupt_id": token,
        "action": "transfer", "payload": {}}, headers=_auth(client, "user_b"))
    assert r.status_code == 400                                  # 防跨会话 resume


def test_select_order_returns_refund_preview_no_ticket(client, user_a, conv_a, db_session):
    token, _ = sign_interrupt(conv_a.id, "order_select")
    r = client.post("/api/chat/resume", json={
        "conversation_id": conv_a.id, "interrupt_id": token,
        "action": "select_order", "payload": {"order_no": "O1", "item_id": "ITEM1"}},
        headers=_auth(client, "user_a"))
    assert r.status_code == 200
    data = r.json()
    assert data["card"]["type"] == "refund_preview"
    assert "退款未真实提交" in data["card"]["payload"]["notice"]   # 诚实：不冒报提交
    assert db_session.query(Ticket).count() == 0
```

- [ ] **Step 2: 运行确认失败** `pytest tests/test_resume_api.py -q` → FAIL
- [ ] **Step 3: 实现最小代码**

```python
# app/schemas.py 追加
class ResumeRequest(BaseModel):
    conversation_id: int
    interrupt_id: str
    action: str                      # transfer | confirm_ticket | select_order | cancel
    payload: dict | None = None
```

```python
# app/api/resume.py
import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.conversations import get_owned_conversation
from app.auth.deps import get_current_user
from app.db import get_db
from app.models import User
from app.schemas import ResumeRequest
from app.tools.builtin import create_ticket_handler
from app.tools.context import ExecutionContext
from app.tools.interrupt import build_card, sign_interrupt, verify_interrupt

router = APIRouter(prefix="/api/chat", tags=["chat"])

_ACTION_CARD = {"transfer": "transfer_human", "confirm_ticket": "ticket_confirm",
                "select_order": "order_select"}


@router.post("/resume")
def resume(req: ResumeRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conv = get_owned_conversation(req.conversation_id, user, db)

    if req.action == "cancel":
        return {"status": "cancelled"}
    card_type = _ACTION_CARD.get(req.action)
    if card_type is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "未知 action")
    payload = verify_interrupt(req.interrupt_id, req.conversation_id, card_type)
    if payload is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "interrupt 无效或已过期（防跨会话）")

    owner = db.get(User, conv.user_id)
    ctx = ExecutionContext(caller_user_id=user.id, caller_role=user.role.value,
                           customer_id=owner.customer_id if owner else None,
                           conversation_id=conv.id, confirmed=True)

    if req.action == "transfer":
        conv.status = "agent_waiting"; db.commit()
        return {"status": "transferred"}
    if req.action == "confirm_ticket":
        p = req.payload or {}
        idem = hashlib.sha256(f"ticket:{conv.id}:{payload['nonce']}".encode()).hexdigest()
        out = create_ticket_handler({"description": p.get("description", ""),
                                     "type": p.get("type", "投诉"), "idempotency_key": idem}, ctx, db)
        return json.loads(out)
    # select_order → 退款预览卡片（D3：不真实提交）
    token, _ = sign_interrupt(conv.id, "refund_preview")
    card = build_card("refund_preview", token, {
        "order_no": (req.payload or {}).get("order_no"),
        "item_id": (req.payload or {}).get("item_id"),
        "notice": "退款未真实提交，如需办理请转人工或建工单。",
    })
    return {"card": card}
```

- [ ] **Step 4: 运行确认通过** `pytest tests/test_resume_api.py -q` → PASS
- [ ] **Step 5: 提交** `git add app/api/resume.py app/schemas.py tests/test_resume_api.py && git commit -m "feat(p4): resume endpoint with idempotency + anti-cross-session"`

---

### Task 10: 工作流接线（真实工具 + 引擎 + 卡片 + SSE card 事件）

**Files:**
- Modify: `app/workflow/graph.py`、`app/api/chat.py`、`app/main.py`
- Test: `tests/test_workflow_tools.py`；修改 `tests/test_workflow_graph.py`、`tests/test_chat_workflow_api.py`、`tests/test_chat_stream.py`

**Interfaces:**
- Consumes: Task 2 `ToolExecutor.agent_tools(ctx)`；Task 7 `build_card`/`sign_interrupt`；Task 1 `ExecutionContext`；Task 3 `register_builtin_tools`
- Produces: `build_workflow(*, chat_model, intent_model, retriever, settings=settings)` — **去掉 `tools` 参数**；节点从 `state["agent_tools"]` 取工具、从 `state["ctx"]` 取身份；分支：商品咨询（RAG→闸→agent）/ 闲聊·其他（固定话术）/ 投诉（transfer_human 卡片）/ 退款退货·售后（order_select 卡片）/ 物流订单（agent 带工具）。`chat.py` 新增 `get_retriever`/`get_tool_registry`，每请求构建 `ctx` + `executor.agent_tools(ctx)` 注入；流中若有 `card` 发 `card` 事件。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_workflow_tools.py
from app.llm.client import IntentResult
from app.llm.fakes import FakeChatModel, FakeIntentModel
from app.rag.retrieval import RetrievalResult, ScoredChunk
from app.tools.context import ExecutionContext
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry, ToolSpec
from app.workflow.graph import build_workflow


class _Rag:
    def retrieve(self, query, top_k=10):
        return RetrievalResult(
            chunks=[ScoredChunk(chunk_id=1, score=0.9, category="政策", section_path="R01",
                                content_type="policy", snippet="七天无理由")],
            evidence_confidence=0.9, passed=True)


def _graph(intent, chat=None, retriever=None):
    intent_model = FakeIntentModel(); intent_model.next_result = IntentResult(intent=intent, confidence=0.9)
    chat_model = chat or FakeChatModel()
    return build_workflow(chat_model=chat_model, intent_model=intent_model,
                          retriever=retriever or _Rag())


def _ctx():
    return ExecutionContext(caller_user_id=1, caller_role="customer",
                            customer_id="C0001", conversation_id=1)


def test_agent_invokes_tool_via_executor(db_session):
    chat = FakeChatModel()
    chat.next_actions = [("tool_call", {"name": "query_product", "args": {}}),
                         ("final", "已查到商品:手机")]
    graph = _graph("物流", chat=chat)
    reg = ToolRegistry()
    reg.register(ToolSpec(name="query_product", description="查商品", input_schema={"type": "object"},
                          source="builtin", handler=lambda a, c, db: "商品:手机"))
    ex = ToolExecutor(reg, db_session)
    out = graph.invoke({"messages": [{"role": "user", "content": "查商品"}],
                        "ctx": _ctx(), "agent_tools": ex.agent_tools(_ctx())})
    assert "手机" in out["answer"]


def test_refund_emits_order_select_card():
    graph = _graph("退款退货")
    out = graph.invoke({"messages": [{"role": "user", "content": "我要退货"}],
                        "ctx": _ctx(), "agent_tools": []})
    assert out.get("card", {}).get("type") == "order_select"
    assert out["card"]["interrupt_id"]


def test_complaint_emits_handoff_card():
    graph = _graph("投诉")
    out = graph.invoke({"messages": [{"role": "user", "content": "我要投诉"}],
                        "ctx": _ctx(), "agent_tools": []})
    assert out["card"]["type"] == "transfer_human"
    assert out["card"]["interrupt_id"]
    assert "已记录" not in out["answer"]
    assert "已受理" not in out["answer"]
```

修改 `tests/test_workflow_graph.py`：顶部加 `from app.tools.context import ExecutionContext` 与 helper：

```python
def _ctx():
    return ExecutionContext(caller_user_id=1, caller_role="customer",
                            customer_id="C0001", conversation_id=1)
```

所有 `build_workflow(..., tools=[])` 去掉 `tools=[]`；所有 `graph.invoke({"messages": [...]})` 增传 `"ctx": _ctx(), "agent_tools": []`。改：
- `test_graph_chitchat_returns_fixed_text_without_model` / `test_graph_product_qa_end_to_end` / `test_graph_product_qa_injects_numbered_evidence` / `test_graph_product_qa_refuses_when_gate_fails`：仅去掉 `tools=[]`、invoke 增传 ctx/agent_tools，断言不变。
- `test_graph_complaint_returns_honest_disclosure` 改为：

```python
def test_graph_complaint_emits_handoff_card():
    intent = FakeIntentModel(); intent.next_result = IntentResult(intent="投诉", confidence=0.9)
    chat = FakeChatModel(); chat.next_text = "不该被调用"
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_Rag())
    out = graph.invoke({"messages": [{"role": "user", "content": "我要投诉你们"}],
                        "ctx": _ctx(), "agent_tools": []})
    ans = out["answer"]
    assert out.get("card", {}).get("type") == "transfer_human"
    assert "转人工" in ans or "转接" in ans       # 诚实指向真人，不冒报已受理
    assert "已记录" not in ans
    assert "已受理" not in ans
```

- `test_graph_logistics_returns_honest_stub` 改为：

```python
def test_graph_logistics_runs_agent():
    intent = FakeIntentModel(); intent.next_result = IntentResult(intent="物流", confidence=0.9)
    chat = FakeChatModel()
    chat.next_actions = [("final", "物流信息如下")]
    graph = build_workflow(chat_model=chat, intent_model=intent, retriever=_Rag())
    out = graph.invoke({"messages": [{"role": "user", "content": "我的快递到哪了"}],
                        "ctx": _ctx(), "agent_tools": []})
    assert out["answer"] == "物流信息如下"        # 物流分支走 agent 而非占位话术
```

- [ ] **Step 2: 运行确认失败** `pytest tests/test_workflow_tools.py -q` → FAIL
- [ ] **Step 3: 实现最小代码**

`app/workflow/graph.py`：

```python
# 顶部新增 import
from app.tools.context import ExecutionContext
from app.tools.interrupt import build_card, sign_interrupt

class WorkflowState(TypedDict):
    messages: Annotated[list, add_messages]
    resolved_text: str
    intent_result: IntentResult
    branch: Branch
    evidence: RetrievalResult
    passed: bool
    answer: str
    citations: list[Citation]
    ctx: ExecutionContext          # 输入态：由 chat.py 注入
    agent_tools: list              # 输入态：由 chat.py 注入
    card: dict | None              # 输出态：投诉/退款分支卡片

# FIXED_TEXTS 只保留 闲聊/其他（投诉改走 _complaint 节点）；删除 HONEST_STUBS。
FIXED_TEXTS = {
    Branch.闲聊: "您好，我是 SayHelp 客服助手，很高兴为您服务。请问有什么可以帮您？",
    Branch.其他: "抱歉，我还不能完全理解您的问题，请您换个方式描述一下，或转人工协助。",
}
```

`build_workflow` 签名去掉 `tools`；节点改动：

```python
    def _product_qa(state: WorkflowState) -> dict:
        r = retriever.retrieve(state["resolved_text"])
        if not r.passed:
            return {"answer": REFUSE_TEXT, "citations": [], "evidence": r, "passed": False}
        cites = build_citations(r.chunks)
        evidence_text = "\n".join(f"[{i}] {c.snippet}" for i, c in enumerate(r.chunks, start=1))
        context = [
            {"role": "user", "content": state["resolved_text"]},
            {"role": "system", "content": "参考资料：\n" + evidence_text},
        ]
        agent_res = run_agent(chat_model, state["agent_tools"], context,
                              max_steps=settings.agent_max_steps,
                              token_budget=settings.agent_token_budget,
                              timeout_s=settings.agent_timeout_s)
        return {"answer": agent_res.answer, "citations": cites, "evidence": r, "passed": True}

    def _logistics_order(state: WorkflowState) -> dict:
        context = [{"role": "user", "content": state["resolved_text"]}]
        agent_res = run_agent(chat_model, state["agent_tools"], context,
                              max_steps=settings.agent_max_steps,
                              token_budget=settings.agent_token_budget,
                              timeout_s=settings.agent_timeout_s)
        return {"answer": agent_res.answer, "citations": []}

    def _refund_aftersales(state: WorkflowState) -> dict:
        token, _ = sign_interrupt(state["ctx"].conversation_id, "order_select")
        return {"answer": "请选择需要办理的订单（退款仅作表单预览，不会真实提交）。",
                "citations": [], "card": build_card("order_select", token, {})}

    def _complaint(state: WorkflowState) -> dict:
        token, _ = sign_interrupt(state["ctx"].conversation_id, "transfer_human")
        return {"answer": "很抱歉给您带来不便。您可以转接人工客服，坐席会尽快为您跟进。",
                "citations": [], "card": build_card("transfer_human", token, {})}

    def _fixed_text(state: WorkflowState) -> dict:
        return {"answer": FIXED_TEXTS.get(state["branch"], FIXED_TEXTS[Branch.其他]), "citations": []}

    def _final(state: WorkflowState) -> dict:
        return {}
```

图组装（替换 `honest_stub` 节点为 `complaint`/`refund_aftersales`/`logistics_order`）：

```python
    graph.add_node("resolve", _resolve)
    graph.add_node("classify", _classify)
    graph.add_node("product_qa", _product_qa)
    graph.add_node("fixed_text", _fixed_text)
    graph.add_node("complaint", _complaint)
    graph.add_node("refund_aftersales", _refund_aftersales)
    graph.add_node("logistics_order", _logistics_order)
    graph.add_node("final", _final)

    graph.add_edge(START, "resolve")
    graph.add_edge("resolve", "classify")
    graph.add_conditional_edges(
        "classify",
        _route_by_branch,
        {
            Branch.商品咨询: "product_qa",
            Branch.闲聊: "fixed_text",
            Branch.其他: "fixed_text",
            Branch.投诉: "complaint",
            Branch.退款退货: "refund_aftersales",
            Branch.售后: "refund_aftersales",
            Branch.物流订单: "logistics_order",
        },
    )
    for node in ("product_qa", "fixed_text", "complaint", "refund_aftersales", "logistics_order"):
        graph.add_edge(node, "final")
    graph.add_edge("final", END)
```

`app/api/chat.py`：新增依赖 + 改 `_build_real_workflow` 与 `chat_stream`：

```python
@functools.lru_cache(maxsize=1)
def get_retriever():
    return _LazyRetriever()


@functools.lru_cache(maxsize=1)
def get_tool_registry():
    from app.mcp.client import McpClient, make_http_transport
    from app.tools.builtin import register_builtin_tools
    from app.tools.registry import ToolRegistry
    registry = ToolRegistry()
    register_builtin_tools(registry, retriever=get_retriever())
    registry.attach_mcp(McpClient(make_http_transport()))
    return registry


def _build_real_workflow():
    from app.llm.client import OpenAIChatModel, JevIntentModel
    from app.workflow.graph import build_workflow
    chat_model = OpenAIChatModel(settings.chat_base_url, settings.chat_model, settings.chat_api_key)
    intent_model = JevIntentModel()
    return build_workflow(chat_model=chat_model, intent_model=intent_model, retriever=get_retriever())
```

`chat_stream` 端点：签名新增 `registry=Depends(get_tool_registry)`；在 `gen()` 之前构建 ctx/agent_tools 并注入 invoke；`gen()` 里发 card 事件：

```python
@router.post("/chat/stream")
def chat_stream(req: ChatStreamRequest, db: Session = Depends(get_db),
                user: User = Depends(get_current_user), workflow=Depends(get_workflow),
                registry=Depends(get_tool_registry)):
    conv = get_owned_conversation(req.conversation_id, user, db)
    conv.updated_at = datetime.now(timezone.utc)
    user_msg = Message(conversation_id=conv.id, role="user", content=req.content)
    db.add(user_msg); db.commit()
    db.refresh(user_msg)

    history = [...同 P3 不变...]

    owner = db.get(User, conv.user_id)
    ctx = build_execution_context(caller=user, owner=owner, conversation=conv)
    executor = ToolExecutor(registry, db)
    agent_tools = executor.agent_tools(ctx)

    def gen():
        yield sse_event("status", {"state": "processing"})
        try:
            state = workflow.invoke({"messages": [*history, {"role": "user", "content": req.content}],
                                     "ctx": ctx, "agent_tools": agent_tools})
            answer = state["answer"]
            citations = state.get("citations", [])
            card = state.get("card")
        except Exception:
            answer = SERVICE_UNAVAILABLE_TEXT
            citations = []
            card = None
            yield sse_event("error", {"message": "服务暂时不可用，请稍后重试"})
        else:
            yield sse_event("text", {"delta": answer})
            if citations:
                yield sse_event("reference", _serialize_citations(citations))
            if card:
                yield sse_event("card", card)
        yield sse_event("done", {})

        assistant = Message(
            conversation_id=conv.id,
            role="assistant",
            content=answer,
            citations=_serialize_citations(citations) if citations else None,
        )
        db.add(assistant); db.commit()

    return StreamingResponse(gen(), media_type="text/event-stream")
```

`chat.py` 顶部新增 import：`from app.tools.context import build_execution_context`、`from app.tools.executor import ToolExecutor`。

`app/main.py`：

```python
from app.api import agent, auth, chat, conversations, resume
...
app.include_router(agent.router)
app.include_router(resume.router)
```

修改两个 fake_workflow fixture（`tests/test_chat_stream.py` 与 `tests/test_chat_workflow_api.py`）：`build_workflow(...)` 去掉 `tools=[]`；并新增覆盖 `get_tool_registry` 返回空注册中心（避免测试触 MCP 网络）：

```python
@pytest.fixture
def fake_workflow():
    from app.api.chat import get_workflow, get_tool_registry
    ...
    from app.tools.registry import ToolRegistry
    ...
    def override():
        return build_workflow(chat_model=chat, intent_model=intent, retriever=_DummyRag())

    def override_registry():
        return ToolRegistry()   # 空注册中心：测试不触 MCP 网络

    app.dependency_overrides[get_workflow] = override
    app.dependency_overrides[get_tool_registry] = override_registry
    try:
        yield {"chat": chat, "intent": intent, ...}
    finally:
        app.dependency_overrides.pop(get_workflow, None)
        app.dependency_overrides.pop(get_tool_registry, None)
```

修改 `test_chat_workflow_api.py::test_chat_stream_logistics_returns_honest_stub` 为 `test_chat_stream_logistics_runs_agent`：

```python
def test_chat_stream_logistics_runs_agent(client, user_a, conv_a, fake_workflow):
    fake_workflow["intent"].next_result = IntentResult(intent="物流", confidence=0.9)
    fake_workflow["chat"].next_actions = [("final", "物流信息如下")]
    headers = _auth(client, "user_a")
    with client.stream("POST", "/api/chat/stream",
                       json={"conversation_id": conv_a.id, "content": "我的快递到哪了"},
                       headers=headers) as r:
        assert r.status_code == 200
        events = parse_sse(r.iter_lines())
    assert [e.type for e in events] == ["status", "text", "done"]
    assert events[1].data == {"delta": "物流信息如下"}
```

修改 `tests/test_chat_stream.py::test_stream_emits_error_and_done_and_persists_on_invoke_failure` 与 `tests/test_chat_workflow_api.py::test_chat_stream_passes_prior_history_to_workflow`：这两个直接覆盖 `get_workflow` 的测试须**同时**覆盖 `get_tool_registry` 返回空 `ToolRegistry()`（否则 chat_stream 会构建真实 MCP 注册中心）：

```python
    from app.api.chat import get_workflow, get_tool_registry
    from app.tools.registry import ToolRegistry
    ...
    app.dependency_overrides[get_workflow] = lambda: _BoomWorkflow()
    app.dependency_overrides[get_tool_registry] = lambda: ToolRegistry()
    ...
    finally:
        app.dependency_overrides.pop(get_workflow, None)
        app.dependency_overrides.pop(get_tool_registry, None)
```

- [ ] **Step 3b: 核实真实 MCP 传输**：`make_http_transport()` 按 `dev-notes/ch08.md` 核实后落地（惰性连接）；测试不触它（fixture 覆盖 `get_tool_registry`）。
- [ ] **Step 4: 运行确认通过** `pytest -q` → 全绿（含改写的三个测试文件）
- [ ] **Step 5: 提交** `git add app/workflow/graph.py app/api/chat.py app/main.py tests/test_workflow_tools.py tests/test_workflow_graph.py tests/test_chat_workflow_api.py tests/test_chat_stream.py && git commit -m "feat(p4): wire tools/engine/cards into chat workflow"`

---

## 范围外（本计划不覆盖，记录备查）

- **jev System One 协议差异**（P3 遗留）：`JevIntentModel` 仍为 OpenAI 兼容占位；P4 不碰意图节点。真实接线前须把 `app/llm/client.py::JevIntentModel` 改为 jev 专用 `/v1/systemone` 客户端，`.env`/`.env.example` 补 `JEV_BASE_URL=https://api.typesafe.ai` + `JEV_API_KEY`（现 `.env` 仅有 `TYPESAFE_API_KEY`）。base 官方 vs DMXAPI 网关仍未定。
- **Milvus/FlagEmbedding 真实数据**：`query_faq`/商品咨询真实检索仍依赖 Milvus 灌库 + BGE 模型（Docker daemon 未启动），P4 测试用 fake；真实路径留待环境就绪。
- **checkpointer/interrupt/resume 挂起语义**（P5）：本计划卡片 resume 是「有状态 resume」而非 LangGraph checkpointer 挂起。
- **坐席/后台 UI**（P6）：P4 只交付坐席后端端点 + 身份字段；可视化后台/坐席界面归 P6。
- **真实 MCP 传输（streamable HTTP 客户端）**：`make_http_transport()` 的 SDK 精确签名在 Task 6/10 实施时经 `dev-notes/ch08.md` 核实；纯工具函数与客户端协议（fake transport）已在本计划内闭环，不依赖真实 SDK 也可全绿。

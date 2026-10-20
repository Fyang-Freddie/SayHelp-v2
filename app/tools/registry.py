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

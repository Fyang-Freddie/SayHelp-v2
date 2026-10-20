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

    mcp SDK 精确签名已核实并记录 dev-notes/ch08.md；本函数是唯一触真实 SDK 的接缝，
    测试不触它（fixture 覆盖 get_tool_registry）。真实实现见 Task 10 Step 3b。
    """
    from mcp.client.streamable_http import streamable_http_client  # 已 ch08 核实
    raise NotImplementedError("make_http_transport 真实实现见 Task 10 Step 3b")

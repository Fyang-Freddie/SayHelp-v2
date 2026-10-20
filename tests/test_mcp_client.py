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


def test_discover_skips_unmapped_customer_tool():
    """未映射 ownership_field 的 requires_customer 工具 fail-closed 不暴露（Review Focus #1）。"""
    tp = _FakeTransport(tools=[
        {"name": "query_logistics", "description": "查物流",
         "inputSchema": {"type": "object"}, "server": "logistics"},
        {"name": "mystery_tool", "description": "未映射的售后工具",
         "inputSchema": {"type": "object"}, "server": "aftersales"},
    ])
    client = McpClient(tp)
    names = {t.name for t in client.list_tools()}
    assert names == {"query_logistics"}

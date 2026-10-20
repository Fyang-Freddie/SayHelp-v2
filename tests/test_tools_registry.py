from app.tools.registry import AgentTool, ToolRegistry, ToolSpec


def _spec(name, **kw):
    kw.setdefault("description", f"{name} desc")
    kw.setdefault("input_schema", {"type": "object"})
    kw.setdefault("source", "builtin")
    return ToolSpec(name=name, **kw)


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

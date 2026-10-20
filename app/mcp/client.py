import asyncio
import logging

from app.config import settings
from app.tools.registry import ToolSpec

logger = logging.getLogger(__name__)

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
            ownership = _OWNERSHIP_FIELD.get((server, name))
            # 白名单（§4.5）：requires_customer 的 MCP 工具若未映射 ownership_field，
            # 引擎侧无法做归属预检 → fail-closed 不暴露（绝不把越权查询风险放开）。
            if ownership is None:
                logger.warning("MCP 工具 %s:%s 未映射归属字段，已跳过（fail-closed）", server, name)
                continue
            specs.append(ToolSpec(
                name=name, description=raw["description"],
                input_schema=raw.get("inputSchema") or {"type": "object"},
                source="mcp", mcp_server=server,
                requires_customer=True,
                ownership_field=ownership,
            ))
        return specs

    def call_tool(self, server: str, name: str, args: dict) -> str:
        return self._transport.call_tool(server, name, args)

    def refresh(self) -> None:
        self._cache = None


def make_http_transport():
    """返回真实 MCP Streamable HTTP 客户端传输（惰性：构造不建连，首次 list_tools 才连）。

    两个 MCP Server（物流/售后）各一个地址（``settings.mcp_logistics_url`` /
    ``settings.mcp_aftersales_url``）。SDK 签名已核实并记录 dev-notes/ch08.md：
    ``streamable_http_client(url, *, http_client=None, terminate_on_close=True)`` 为异步
    上下文管理器，配合 ``ClientSession(read, write).list_tools()/.call_tool(name, args)``。

    本函数是唯一触真实 SDK 的接缝，测试不触它（fixture 覆盖 ``get_tool_registry`` 返回
    空注册中心）。未配置地址时 ``list_tools()`` 诚实返回空列表（不伪造物流/售后工具），
    ``call_tool()`` 抛错由 ``ToolExecutor`` 收敛为诚实降级。
    """
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    _SERVERS = (
        ("logistics", settings.mcp_logistics_url),
        ("aftersales", settings.mcp_aftersales_url),
    )

    def _list_tools(server: str, url: str) -> list[dict]:
        async def _run():
            async with streamable_http_client(url) as (read, write, _get_session_id):
                session = ClientSession(read, write)
                await session.initialize()
                result = await session.list_tools()
                return [{"name": t.name, "description": t.description or "",
                         "inputSchema": t.inputSchema or {"type": "object"},
                         "server": server}
                        for t in result.tools]
        return asyncio.run(_run())

    def _call_tool(server: str, url: str, name: str, args: dict) -> str:
        async def _run():
            async with streamable_http_client(url) as (read, write, _get_session_id):
                session = ClientSession(read, write)
                await session.initialize()
                result = await session.call_tool(name, args or {})
                parts = []
                for block in result.content:
                    if getattr(block, "type", None) == "text":
                        parts.append(block.text)
                    else:
                        parts.append(str(block))
                return "\n".join(parts) if parts else ""
        return asyncio.run(_run())

    class _StreamableHttpTransport:
        def __init__(self):
            self._servers = [(name, url) for name, url in _SERVERS if url]

        def list_tools(self) -> list[dict]:
            tools: list[dict] = []
            for server, url in self._servers:
                try:
                    tools.extend(_list_tools(server, url))
                except Exception as exc:  # 连不上/未部署 → 诚实降级，不伪造该 Server 工具
                    logger.warning("MCP Server %s 发现失败，暂不暴露其工具：%s", server, exc)
            return tools

        def call_tool(self, server: str, name: str, args: dict) -> str:
            for s, url in self._servers:
                if s == server:
                    return _call_tool(server, url, name, args)
            raise RuntimeError(f"未接入 MCP Server {server}")

    return _StreamableHttpTransport()

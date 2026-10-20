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
            return self._audit(spec, args, ctx, ToolStatus.failure,
                               error=f"工具执行失败：{exc}", started=started)

    def agent_tools(self, ctx) -> list[AgentTool]:
        return [
            AgentTool(name=s.name, description=s.description,
                      run=lambda args, n=s.name: self.execute(n, args, ctx))
            for s in self.registry.list_for_agent()
        ]

import hashlib
import json
import secrets
import time
from datetime import datetime

from app.models import Order, Product, Ticket
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
    registry.register(ToolSpec(
        name="create_ticket", description="创建人工工单（需用户确认）",
        input_schema={"type": "object",
                      "properties": {"description": {"type": "string"},
                                     "type": {"type": "string"},
                                     "idempotency_key": {"type": "string"}},
                      "required": ["description"]},
        source="builtin", is_write=True, visible_to_agent=False,
        handler=create_ticket_handler))

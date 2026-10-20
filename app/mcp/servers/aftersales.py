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
    from mcp.server.fastmcp import FastMCP  # 见 dev-notes/ch08.md 核实
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

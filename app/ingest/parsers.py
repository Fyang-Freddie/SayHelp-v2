from datetime import datetime
from decimal import Decimal

from app.ingest.markdown_table import parse_markdown_table

_TS = "%Y-%m-%d %H:%M:%S"


def _dt(s: str) -> datetime | None:
    s = s.strip()
    if s in ("", "不适用", "未签收"):
        return None
    return datetime.strptime(s, _TS)


def parse_orders(md_text: str) -> list[dict]:
    _, rows = parse_markdown_table(md_text) or ([], [])
    out = []
    for r in rows:
        out.append({
            "customer_id": r[0],
            "order_no": r[1],
            "item_id": r[2],
            "product_name": r[3],
            "model_spec": r[4],
            "quantity": int(r[5]),
            "paid_amount": Decimal(r[6]),
            "order_time": datetime.strptime(r[7], _TS),
            "sign_time": _dt(r[8]),
            "order_status": r[9],
            "after_sale_status": r[10],
        })
    return out


def parse_logistics(md_text: str) -> list[dict]:
    _, rows = parse_markdown_table(md_text) or ([], [])
    out = []
    for r in rows:
        out.append({
            "order_no": r[0],
            "item_ids": r[1],
            "waybill_no": r[2],
            "logistics_type": r[3],
            "carrier": r[4],
            "status": r[5],
            "latest_time": datetime.strptime(r[6], _TS),
            "is_latest": r[7] == "是",
            "trajectory": r[8],
        })
    return out


def parse_products(md_text: str) -> list[dict]:
    _, rows = parse_markdown_table(md_text) or ([], [])
    return [{
        "product_name": r[0], "model": r[1], "order_spec": r[2],
        "product_type": r[3], "seven_day_return": r[4], "warranty": r[5],
    } for r in rows]


def parse_refund_reasons(md_text: str) -> list[dict]:
    _, rows = parse_markdown_table(md_text) or ([], [])
    return [{"code": r[0], "display_name": r[1]} for r in rows]

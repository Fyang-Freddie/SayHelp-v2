from datetime import datetime
from decimal import Decimal

from app.ingest.parsers import (
    parse_logistics, parse_orders, parse_products, parse_refund_reasons,
)


def _read(project_root, name):
    return (project_root / "knowledge_db" / name).read_text(encoding="utf-8")


def test_parse_orders_counts_and_key_values(project_root):
    orders = parse_orders(_read(project_root, "orders.md"))
    assert len(orders) == 100
    assert len({o["order_no"] for o in orders}) == 82
    assert len({o["customer_id"] for o in orders}) == 26
    first = orders[0]
    assert first["customer_id"] == "C0016"
    assert first["order_no"] == "TB202611000001"
    assert first["item_id"] == "ITEM00001"
    assert first["paid_amount"] == Decimal("139.00")
    assert first["order_time"] == datetime(2026, 9, 24, 6, 31, 27)


def test_parse_orders_virtual_goods_sign_time_none(project_root):
    orders = parse_orders(_read(project_root, "orders.md"))
    virtual = {o["item_id"]: o for o in orders}
    assert virtual["ITEM00037"]["sign_time"] is None  # 软件激活码
    assert virtual["ITEM00038"]["sign_time"] is None  # 在线课程兑换码
    assert virtual["ITEM00001"]["sign_time"] == datetime(2026, 9, 27, 7, 45, 49)


def test_parse_orders_not_signed_sign_time_none(project_root):
    orders = parse_orders(_read(project_root, "orders.md"))
    by_item = {o["item_id"]: o for o in orders}
    assert by_item["ITEM00065"]["sign_time"] is None  # 运输中，未签收
    none_count = sum(1 for o in orders if o["sign_time"] is None)
    assert none_count == 23  # 2 虚拟商品「不适用」 + 21 「未签收」


def test_parse_logistics_counts_and_multi_item(project_root):
    rows = parse_logistics(_read(project_root, "logistics.md"))
    assert len(rows) == 200
    assert rows[0]["item_ids"] == "ITEM00001、ITEM00002"  # 顿号整体保留
    assert rows[0]["is_latest"] is False
    latest = [r for r in rows if r["is_latest"]]
    assert len(latest) == 88  # 每运单一条最新


def test_parse_products_only_index_table(project_root):
    products = parse_products(_read(project_root, "product-specifications.md"))
    assert len(products) == 40
    assert products[0]["model"] == "MM-E100"
    assert all(p["model"].startswith("MM-") for p in products)


def test_parse_refund_reasons_counts(project_root):
    reasons = parse_refund_reasons(_read(project_root, "refund-reasons.md"))
    assert len(reasons) == 50
    assert reasons[0] == {"code": "no_longer_needed", "display_name": "不想要了"}
    assert reasons[-1]["code"] == "other"

import json
from datetime import datetime

from app.models import Logistics, Order, Product
from app.mcp.servers.logistics import query_logistics_fn
from app.mcp.servers.aftersales import query_warranty_fn, query_return_progress_fn


def test_query_logistics_prefers_latest(db_session):
    db_session.add_all([
        Logistics(order_no="O1", item_ids="ITEM1", waybill_no="W1", logistics_type="正向",
                  carrier="顺丰", status="已签收", latest_time=datetime(2026, 10, 1),
                  is_latest=False, trajectory="旧轨迹"),
        Logistics(order_no="O1", item_ids="ITEM1", waybill_no="W2", logistics_type="正向",
                  carrier="顺丰", status="运输中", latest_time=datetime(2026, 10, 2),
                  is_latest=True, trajectory="新轨迹"),
    ])
    db_session.commit()
    out = json.loads(query_logistics_fn(db_session, "O1"))
    assert out["status"] == "运输中"
    assert out["trajectory"] == "新轨迹"


def test_query_warranty_in_warranty(db_session):
    db_session.add(Product(product_name="手机", model="M1", order_spec="128G",
                           product_type="数码", seven_day_return="支持", warranty="12个月"))
    db_session.add(Order(customer_id="C1", order_no="O1", item_id="ITEM1", product_name="手机",
                         model_spec="M1", quantity=1, paid_amount=1999, order_status="已签收",
                         after_sale_status="无售后", order_time=datetime(2026, 1, 1),
                         sign_time=datetime(2026, 10, 1)))
    db_session.commit()
    out = json.loads(query_warranty_fn(db_session, "ITEM1"))
    assert out["warranty"] == "12个月"
    assert out["in_warranty"] is True


def test_query_return_progress(db_session):
    db_session.add(Logistics(order_no="O1", item_ids="ITEM1", waybill_no="R1", logistics_type="退货",
                             carrier="圆通", status="已签收", latest_time=datetime(2026, 10, 3),
                             is_latest=True, trajectory="退货已签收"))
    db_session.commit()
    out = json.loads(query_return_progress_fn(db_session, "O1"))
    assert out["status"] == "已签收"

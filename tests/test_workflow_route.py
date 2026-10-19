import pytest
from app.workflow.route import Branch, route


@pytest.mark.parametrize("intent,expected", [
    ("商品咨询", Branch.商品咨询),
    ("退款退货", Branch.退款退货),
    ("售后", Branch.售后),
    ("物流", Branch.物流订单),
    ("订单", Branch.物流订单),
    ("投诉", Branch.投诉),
    ("闲聊", Branch.闲聊),
    ("其他", Branch.其他),
    ("不存在", Branch.其他),
])
def test_route_maps_every_intent(intent, expected):
    assert route(intent) is expected

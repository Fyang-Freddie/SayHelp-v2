"""确定性分流：把意图字符串映射到 7 个处理分支。"""
from enum import Enum


class Branch(str, Enum):
    商品咨询 = "商品咨询"
    退款退货 = "退款退货"
    售后 = "售后"
    物流订单 = "物流订单"
    投诉 = "投诉"
    闲聊 = "闲聊"
    其他 = "其他"


_ROUTE = {
    "商品咨询": Branch.商品咨询,
    "退款退货": Branch.退款退货,
    "售后": Branch.售后,
    "物流": Branch.物流订单,   # 物流、订单合并为单一「物流订单」支（spec §4.3）
    "订单": Branch.物流订单,
    "投诉": Branch.投诉,
    "闲聊": Branch.闲聊,
    "其他": Branch.其他,
}


def route(intent: str) -> Branch:
    """意图 → 分支；未知意图兜底「其他」。"""
    return _ROUTE.get(intent, Branch.其他)

import json

from app.models import Logistics


def query_logistics_fn(db, order_no: str) -> str:
    rows = (db.query(Logistics).filter(Logistics.order_no == order_no)
            .order_by(Logistics.is_latest.desc(), Logistics.latest_time.desc()).all())
    if not rows:
        return json.dumps({"found": False}, ensure_ascii=False)
    r = rows[0]
    return json.dumps({"found": True, "order_no": r.order_no, "waybill_no": r.waybill_no,
                       "logistics_type": r.logistics_type, "carrier": r.carrier,
                       "status": r.status, "latest_time": r.latest_time.isoformat(),
                       "trajectory": r.trajectory}, ensure_ascii=False)


def build_mcp_server():
    from mcp.server.fastmcp import FastMCP  # 见 dev-notes/ch08.md 核实
    mcp = FastMCP("sayhelp-logistics")

    @mcp.tool()
    def query_logistics(order_no: str) -> str:
        from app.db import SessionLocal
        with SessionLocal() as db:
            return query_logistics_fn(db, order_no)

    return mcp


if __name__ == "__main__":
    build_mcp_server().run()

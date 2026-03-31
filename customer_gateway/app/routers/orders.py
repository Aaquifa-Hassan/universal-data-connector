"""
Order endpoints — all require a valid Bearer API key.

GET /api/v1/orders/{order_id}
"""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import require_api_key
from app.db import sf
from app.models import GatewayResponse, OrderDetailResponse, LineItem

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Orders"])

_ID_RE = re.compile(r"\d+")


def _clean_id(raw: str) -> str:
    match = _ID_RE.search(str(raw))
    if not match:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "INVALID_ID", "message": f"'{raw}' is not a valid numeric ID."},
        )
    return match.group(0)


# ─────────────────────────────────────────────────────────────────────────────
#  GET /orders/{order_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/orders/{order_id}",
    response_model=GatewayResponse,
    summary="Fetch full order details including line items",
)
async def get_order(
    order_id: str,
    _: str = Depends(require_api_key),
):
    oid = _clean_id(order_id)
    logger.info("[GATEWAY] GET /orders/%s", oid)

    result = await sf.fetch_order_with_items(oid)
    order_row = result.get("order", {})
    if not order_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "NOT_FOUND",
                "message": f"Order {oid} does not exist.",
            },
        )

    items = [
        LineItem(
            item_id=str(r.get("item_id", "")),
            product_name=str(r.get("product_name", "")),
            quantity=r.get("quantity"),
            unit_price=r.get("unit_price"),
            return_flag=r.get("return_flag"),
            line_status=r.get("line_status"),
        ).model_dump(exclude_none=True)
        for r in result.get("line_items", [])
    ]

    payload = OrderDetailResponse(
        order_id=f"ORD-{order_row.get('order_id', oid)}",
        customer_id=f"CUST-{order_row['customer_id']}" if order_row.get("customer_id") else None,
        status=order_row.get("status"),
        order_date=order_row.get("order_date"),
        total_price=order_row.get("total_price"),
        priority=order_row.get("priority"),
        line_items=items,
    )
    return GatewayResponse(
        success=True,
        data=payload.model_dump(exclude_none=True),
        message=f"Order {oid} retrieved with {len(items)} line item(s).",
    )

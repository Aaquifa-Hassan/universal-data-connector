"""
Customer endpoints — all require a valid Bearer API key.

GET /api/v1/customers/{customer_id}
GET /api/v1/customers/{customer_id}/orders
GET /api/v1/customers/{customer_id}/tickets
"""
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import require_api_key
from app.db import sf
from app.models import (
    GatewayResponse,
    CustomerProfile,
    CustomerOrdersResponse,
    OrderSummary,
    CustomerTicketsResponse,
    TicketSummary,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Customers"])

_ID_RE = re.compile(r"\d+")


def _clean_id(raw: str) -> str:
    """Strip non-numeric characters, raise 422 if nothing is left."""
    match = _ID_RE.search(str(raw))
    if not match:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "INVALID_ID", "message": f"'{raw}' is not a valid numeric ID."},
        )
    return match.group(0)


# ─────────────────────────────────────────────────────────────────────────────
#  GET /customers/{customer_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/customers/{customer_id}",
    response_model=GatewayResponse,
    summary="Look up a customer by ID",
)
async def get_customer(
    customer_id: str,
    _: str = Depends(require_api_key),
):
    cid = _clean_id(customer_id)
    logger.info("[GATEWAY] GET /customers/%s", cid)

    row = await sf.fetch_customer(cid)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "NOT_FOUND",
                "message": f"Customer {cid} does not exist.",
            },
        )

    profile = CustomerProfile(
        customer_id=f"CUST-{row['customer_id']}",
        name=row.get("name", ""),
        phone=row.get("phone"),
        address=row.get("address"),
        market_segment=row.get("market_segment"),
        account_balance=row.get("account_balance"),
        nation_key=row.get("nation_key"),
        found=True,
    )
    return GatewayResponse(
        success=True,
        data=profile.model_dump(exclude_none=True),
        message=f"Customer {cid} found.",
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /customers/{customer_id}/orders
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/customers/{customer_id}/orders",
    response_model=GatewayResponse,
    summary="Fetch recent orders for a customer",
)
async def get_customer_orders(
    customer_id: str,
    limit: int = Query(default=5, ge=1, le=50, description="Max number of orders to return"),
    status: Optional[str] = Query(default="ALL", description="Filter by status: OPEN, CLOSED, ALL"),
    _: str = Depends(require_api_key),
):
    cid = _clean_id(customer_id)
    logger.info("[GATEWAY] GET /customers/%s/orders limit=%s status=%s", cid, limit, status)

    rows = await sf.fetch_customer_orders(cid, limit=limit, status=status or "ALL")
    orders = [
        OrderSummary(
            order_id=f"ORD-{r['order_id']}",
            order_date=r.get("order_date"),
            total_price=r.get("total_price"),
            status=r.get("status"),
            priority=r.get("priority"),
        ).model_dump(exclude_none=True)
        for r in rows
    ]
    payload = CustomerOrdersResponse(
        customer_id=f"CUST-{cid}",
        orders=orders,
        total_count=len(orders),
    )
    return GatewayResponse(
        success=True,
        data=payload.model_dump(),
        message=f"Found {len(orders)} orders for customer {cid}.",
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /customers/{customer_id}/tickets
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/customers/{customer_id}/tickets",
    response_model=GatewayResponse,
    summary="Fetch support tickets for a customer",
)
async def get_customer_tickets(
    customer_id: str,
    status: Optional[str] = Query(default="OPEN", description="Filter: OPEN, CLOSED, ALL"),
    _: str = Depends(require_api_key),
):
    cid = _clean_id(customer_id)
    logger.info("[GATEWAY] GET /customers/%s/tickets status=%s", cid, status)

    rows = await sf.fetch_customer_tickets(cid, status=status or "OPEN")
    tickets = [
        TicketSummary(
            ticket_id=r["ticket_id"],
            subject=r.get("subject"),
            status=r.get("status"),
            priority=r.get("priority"),
            created_at=r.get("created_at"),
        ).model_dump(exclude_none=True)
        for r in rows
    ]
    payload = CustomerTicketsResponse(
        customer_id=f"CUST-{cid}",
        tickets=tickets,
        total_count=len(tickets),
    )
    return GatewayResponse(
        success=True,
        data=payload.model_dump(),
        message=f"Found {len(tickets)} tickets for customer {cid}.",
    )

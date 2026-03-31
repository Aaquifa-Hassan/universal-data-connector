"""
Pydantic models — request and response shapes for the Customer Data API Gateway.

These form the CONTRACT between customer's gateway and the Universal Data Connector.
Both sides must agree on these shapes. Change them carefully.
"""
from pydantic import BaseModel, Field
from typing import Any, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
#  Shared envelope
# ─────────────────────────────────────────────────────────────────────────────

class GatewayResponse(BaseModel):
    """Standard response envelope returned by every endpoint."""
    success: bool
    data: Any
    message: str = "OK"


# ─────────────────────────────────────────────────────────────────────────────
#  Customer
# ─────────────────────────────────────────────────────────────────────────────

class CustomerProfile(BaseModel):
    customer_id: str                         # e.g. "CUST-12345"
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    market_segment: Optional[str] = None
    account_balance: Optional[float] = None
    nation_key: Optional[int] = None
    found: bool = True


# ─────────────────────────────────────────────────────────────────────────────
#  Orders
# ─────────────────────────────────────────────────────────────────────────────

class OrderSummary(BaseModel):
    order_id: str                            # e.g. "ORD-77001"
    order_date: Optional[str] = None
    total_price: Optional[float] = None
    status: Optional[str] = None
    priority: Optional[str] = None


class CustomerOrdersResponse(BaseModel):
    customer_id: str
    orders: List[OrderSummary]
    total_count: int


class LineItem(BaseModel):
    item_id: Optional[str] = None
    product_name: Optional[str] = None
    quantity: Optional[int] = None
    unit_price: Optional[float] = None
    return_flag: Optional[str] = None
    line_status: Optional[str] = None


class OrderDetailResponse(BaseModel):
    order_id: str
    customer_id: Optional[str] = None
    status: Optional[str] = None
    order_date: Optional[str] = None
    total_price: Optional[float] = None
    priority: Optional[str] = None
    line_items: List[LineItem] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
#  Support Tickets
# ─────────────────────────────────────────────────────────────────────────────

class TicketSummary(BaseModel):
    ticket_id: str
    subject: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    created_at: Optional[str] = None


class CustomerTicketsResponse(BaseModel):
    customer_id: str
    tickets: List[TicketSummary]
    total_count: int


# ─────────────────────────────────────────────────────────────────────────────
#  Errors  (returned by _handle_response in RestApiConnector)
# ─────────────────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    error: str      # e.g. "NOT_FOUND", "UNAUTHORIZED", "DATALAKE_ERROR"
    message: str
    request_id: Optional[str] = None
    retry_after: Optional[int] = None   # seconds, only for 429

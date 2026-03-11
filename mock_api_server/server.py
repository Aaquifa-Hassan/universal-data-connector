"""
Standalone mock API server — runs on port 8001.
Mimics Salesforce (CRM), Freshdesk (Support), and Analytics APIs.

Start with:
    uvicorn mock_api_server.server:app --port 8001 --reload
"""

from datetime import date, timedelta, datetime
from typing import Optional, List
from fastapi import FastAPI, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
import random

from mock_api_server.database import init_db, get_db, Customer, Order, Product, Ticket, Case
from mock_api_server.data import CUSTOMERS, ORDERS, PRODUCTS, TICKETS

# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Mock CRM & Support API", version="1.0.0")

# ── Priority → ETA mapping ─────────────────────────────────────────────────────
PRIORITY_ETA = {1: 1, 2: 3, 3: 7, 4: 14}   # days
PRIORITY_LABEL = {1: "urgent", 2: "high", 3: "medium", 4: "low"}

# ── Resolution logic ───────────────────────────────────────────────────────────
REFUND_CATEGORIES = {"food", "pharma", "grocery"}
EXCHANGE_CATEGORIES = {"electronics", "appliances", "gadgets"}


def decide_resolution(category: str) -> str:
    cat = category.lower()
    if cat in REFUND_CATEGORIES:
        return "refund"
    if cat in EXCHANGE_CATEGORIES:
        return "exchange"
    return "refund"  # default to refund for unknown


def is_expired(expiry_date_str: str) -> bool:
    try:
        expiry = date.fromisoformat(expiry_date_str)
        return expiry < date.today()
    except Exception:
        return False


def is_under_warranty(purchase_date_str: str, warranty_months: int) -> bool:
    if warranty_months == 0:
        return False
    try:
        purchase = date.fromisoformat(purchase_date_str)
        expiry = purchase + timedelta(days=warranty_months * 30)
        return date.today() <= expiry
    except Exception:
        return False


# ── Startup: seed DB if empty ──────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    init_db()
    db = next(get_db())
    try:
        if db.query(Customer).count() == 0:
            for c in CUSTOMERS:
                db.add(Customer(**c))
            for o in ORDERS:
                db.add(Order(**o))
            for p in PRODUCTS:
                db.add(Product(**p))
            for t in TICKETS:
                db.add(Ticket(**t))
            db.commit()
            print("✅ Mock DB seeded.")
        else:
            print("✅ Mock DB already seeded, skipping.")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
#  CRM endpoints (Salesforce-like)
# ══════════════════════════════════════════════════════════════════════════════

# ── GET /crm/contacts ──────────────────────────────────────────────────────────

@app.get("/crm/contacts")
def list_contacts(limit: int = Query(10, ge=1, le=100), db: Session = Depends(get_db)):
    """List customers — used by CRMConnector for /data/crm."""
    customers = db.query(Customer).limit(limit).all()
    return [
        {
            "customer_id": c.id,
            "name": c.name,
            "email": c.email,
            "segment": c.segment,
            "account_since": c.account_since,
            "status": "active",
        }
        for c in customers
    ]


# ── Request models ─────────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    customer_id: str

class RefundRequest(BaseModel):
    order_id: str
    customer_id: str
    reason: Optional[str] = "Customer request"

class ExchangeRequest(BaseModel):
    order_id: str
    customer_id: str
    reason: Optional[str] = "Customer request"


# ── POST /crm/authenticate ────────────────────────────────────────────────────

@app.post("/crm/authenticate")
def authenticate(req: AuthRequest, db: Session = Depends(get_db)):
    cid = req.customer_id.upper().strip()
    customer = db.query(Customer).filter(Customer.id == cid).first()
    if not customer:
        return {
            "success": False,
            "data": {},
            "message": "No account found with that ID. Please double-check your customer number.",
        }
    return {
        "success": True,
        "data": {
            "id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "segment": customer.segment,
            "account_since": customer.account_since,
        },
        "message": f"Identity verified. Welcome, {customer.name.split()[0]}!",
    }


# ── GET /crm/orders/{order_id} ─────────────────────────────────────────────────

@app.get("/crm/orders/{order_id}")
def get_order(order_id: str, customer_id: str, db: Session = Depends(get_db)):
    oid = order_id.upper().strip()
    cid = customer_id.upper().strip()

    order = db.query(Order).filter(Order.id == oid).first()
    if not order:
        return {
            "success": False,
            "data": {},
            "message": f"No order found with ID {oid}. Could you double-check the order number?",
        }

    # Ownership check — prevent LLM hallucinations from leaking cross-customer data
    if order.customer_id.upper() != cid:
        return {
            "success": False,
            "data": {},
            "message": "That order doesn't appear to be linked to your account.",
        }

    product = db.query(Product).filter(Product.order_id == oid).first()
    expired = False
    recommended_resolution = None
    in_warranty = False
    product_data = {}

    if product:
        expired = is_expired(product.expiry_date)
        in_warranty = is_under_warranty(order.purchase_date, product.warranty_months)
        if expired or in_warranty:
            recommended_resolution = decide_resolution(product.category)
        product_data = {
            "name": product.name,
            "category": product.category,
            "expiry_date": product.expiry_date,
            "warranty_months": product.warranty_months,
            "in_warranty": in_warranty,
        }

    if expired:
        msg = (
            f"Your {product.name} (order {oid}) expired on {product.expiry_date}. "
            f"Recommended resolution: {recommended_resolution}."
        )
    elif order.delivery_status == "In Transit":
        msg = f"Your order {oid} is currently in transit and should arrive within 2–3 business days."
    else:
        msg = f"Your order {oid} was delivered and is in good standing."

    return {
        "success": True,
        "data": {
            "order_id": order.id,
            "customer_id": order.customer_id,
            "status": order.status,
            "purchase_date": order.purchase_date,
            "amount": order.amount,
            "delivery_status": order.delivery_status,
            "product": product_data,
            "expired": expired,
            "recommended_resolution": recommended_resolution,
        },
        "message": msg,
    }


# ── GET /crm/customers/{customer_id} ──────────────────────────────────────────

@app.get("/crm/customers/{customer_id}")
def get_customer(customer_id: str, db: Session = Depends(get_db)):
    cid = customer_id.upper().strip()
    customer = db.query(Customer).filter(Customer.id == cid).first()
    if not customer:
        return {"success": False, "data": {}, "message": f"Customer {cid} not found."}
    return {
        "success": True,
        "data": {
            "customer_id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "segment": customer.segment,
            "account_since": customer.account_since,
        },
        "message": f"Here is the profile for {customer.name}.",
    }


# ── PUT /crm/customers/{customer_id} ──────────────────────────────────────────

class CustomerUpdate(BaseModel):
    name:    Optional[str] = None
    email:   Optional[str] = None
    segment: Optional[str] = None

@app.put("/crm/customers/{customer_id}")
def update_customer(customer_id: str, req: CustomerUpdate, db: Session = Depends(get_db)):
    cid = customer_id.upper().strip()
    customer = db.query(Customer).filter(Customer.id == cid).first()
    if not customer:
        return {"success": False, "data": {}, "message": f"Customer {cid} not found."}
    if req.name:    customer.name    = req.name
    if req.email:   customer.email   = req.email
    if req.segment: customer.segment = req.segment
    db.commit()
    return {
        "success": True,
        "data": {"customer_id": cid, "updated": True},
        "message": "Profile updated successfully.",
    }


# ── GET /crm/customers/{customer_id}/orders ───────────────────────────────────

@app.get("/crm/customers/{customer_id}/orders")
def list_customer_orders(customer_id: str, limit: int = 5, db: Session = Depends(get_db)):
    cid = customer_id.upper().strip()
    orders = db.query(Order).filter(Order.customer_id == cid).limit(limit).all()
    result = []
    for o in orders:
        product = db.query(Product).filter(Product.order_id == o.id).first()
        product_data = {}
        if product:
            expired = is_expired(product.expiry_date) if product.expiry_date else False
            in_warranty = is_under_warranty(o.purchase_date, product.warranty_months)
            product_data = {
                "name": product.name,
                "category": product.category,
                "expiry_date": product.expiry_date,
                "warranty_months": product.warranty_months,
                "expired": expired,
                "in_warranty": in_warranty,
                "recommended_resolution": decide_resolution(product.category) if (expired or in_warranty) else None,
            }
        result.append({
            "order_id": o.id,
            "customer_id": o.customer_id,
            "status": o.status,
            "purchase_date": o.purchase_date,
            "amount": o.amount,
            "delivery_status": o.delivery_status,
            "product": product_data,
        })
    return {
        "success": True,
        "data": result,
        "message": f"Found {len(result)} order(s) on your account.",
    }


# ── POST /crm/cases (generic case) ────────────────────────────────────────────

class CaseRequest(BaseModel):
    customer_id: str
    order_id:    Optional[str] = None
    subject:     Optional[str] = None
    description: Optional[str] = None
    category:    str = "generic"   # refund | exchange | delivery | billing | warranty | generic

@app.post("/crm/cases")
def create_case(req: CaseRequest, db: Session = Depends(get_db)):
    cid = req.customer_id.upper().strip()
    count = db.query(Case).count()
    case = Case(
        order_id=req.order_id,
        customer_id=cid,
        type=req.category,
        reason=req.description or req.subject or req.category,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return {
        "success": True,
        "data": {"case_id": case.id, "customer_id": cid, "type": req.category},
        "message": f"{req.category.capitalize()} case logged successfully.",
    }


# ── POST /crm/refund ───────────────────────────────────────────────────────────

@app.post("/crm/refund")
def initiate_refund(req: RefundRequest, db: Session = Depends(get_db)):
    oid = req.order_id.upper().strip()
    cid = req.customer_id.upper().strip()

    order = db.query(Order).filter(Order.id == oid, Order.customer_id == cid).first()
    if not order:
        return {
            "success": False,
            "data": {},
            "message": "Order not found or doesn't belong to this account.",
        }

    case = Case(order_id=oid, customer_id=cid, type="refund", reason=req.reason)
    db.add(case)
    order.status = "Refund Initiated"
    db.commit()
    db.refresh(case)

    return {
        "success": True,
        "data": {"case_id": case.id, "order_id": oid, "type": "refund"},
        "message": (
            f"Refund initiated for order {oid}. "
            "You'll receive the amount back within 3–5 business days."
        ),
    }


# ── POST /crm/exchange ─────────────────────────────────────────────────────────

@app.post("/crm/exchange")
def initiate_exchange(req: ExchangeRequest, db: Session = Depends(get_db)):
    oid = req.order_id.upper().strip()
    cid = req.customer_id.upper().strip()

    order = db.query(Order).filter(Order.id == oid, Order.customer_id == cid).first()
    if not order:
        return {
            "success": False,
            "data": {},
            "message": "Order not found or doesn't belong to this account.",
        }

    case = Case(order_id=oid, customer_id=cid, type="exchange", reason=req.reason)
    db.add(case)
    order.status = "Exchange Initiated"
    db.commit()
    db.refresh(case)

    return {
        "success": True,
        "data": {"case_id": case.id, "order_id": oid, "type": "exchange"},
        "message": (
            f"Exchange initiated for order {oid}. "
            "A replacement will be dispatched within 2–3 business days."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Support endpoints (Freshdesk-like)
# ══════════════════════════════════════════════════════════════════════════════

class NewTicketRequest(BaseModel):
    customer_id: str
    subject: str
    description: str
    email: Optional[str] = None
    priority: Optional[int] = 3   # 1=urgent 2=high 3=medium 4=low


# ── GET /support/tickets/{ticket_id} ──────────────────────────────────────────

@app.get("/support/tickets/{ticket_id}")
def get_ticket(ticket_id: str, customer_id: Optional[str] = None, db: Session = Depends(get_db)):
    tid = ticket_id.upper().strip()
    ticket = db.query(Ticket).filter(Ticket.id == tid).first()
    if not ticket:
        return {
            "success": False,
            "data": {},
            "message": f"No ticket found with ID {tid}.",
        }

    eta_days = PRIORITY_ETA.get(ticket.priority, 7)
    priority_label = PRIORITY_LABEL.get(ticket.priority, "medium")
    eta_desc = f"{eta_days} business day{'s' if eta_days != 1 else ''}"

    if ticket.status in ("resolved", "closed"):
        msg = f"Ticket {tid} has been {ticket.status}. Is there anything else I can help you with?"
    else:
        msg = (
            f"Ticket {tid} is currently {ticket.status} with {priority_label} priority. "
            f"Expected resolution within {eta_desc}."
        )

    return {
        "success": True,
        "data": {
            "ticket_id": ticket.id,
            "customer_id": ticket.customer_id,
            "subject": ticket.subject,
            "priority": ticket.priority,
            "priority_label": priority_label,
            "status": ticket.status,
            "eta_days": eta_days,
        },
        "message": msg,
    }


# ── POST /support/tickets ──────────────────────────────────────────────────────

@app.post("/support/tickets")
def create_ticket(req: NewTicketRequest, db: Session = Depends(get_db)):
    cid = req.customer_id.upper().strip()

    # Find next ticket ID
    count = db.query(Ticket).count()
    new_id = f"TICK-{1001 + count}"

    ticket = Ticket(
        id=new_id,
        customer_id=cid,
        subject=req.subject,
        description=req.description,
        priority=req.priority,
        status="open",
    )
    db.add(ticket)
    db.commit()

    priority_label = PRIORITY_LABEL.get(req.priority, "medium")
    eta_days = PRIORITY_ETA.get(req.priority, 7)

    return {
        "success": True,
        "data": {
            "ticket_id": new_id,
            "customer_id": cid,
            "subject": req.subject,
            "priority": req.priority,
            "priority_label": priority_label,
            "status": "open",
            "eta_days": eta_days,
        },
        "message": (
            f"Support ticket {new_id} has been raised for '{req.subject}'. "
            f"Our team will look into it within {eta_days} business day{'s' if eta_days != 1 else ''}."
        ),
    }


# ── GET /support/tickets ──────────────────────────────────────────────────────

@app.get("/support/tickets")
def list_tickets(
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    priority: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """List tickets — used by SupportConnector for /data/support."""
    query = db.query(Ticket)
    if status:
        query = query.filter(Ticket.status == status)
    if priority is not None:
        query = query.filter(Ticket.priority == priority)
    tickets = query.limit(limit).all()
    return [
        {
            "ticket_id": t.id,
            "customer_id": t.customer_id,
            "subject": t.subject,
            "description": t.description,
            "priority": t.priority,
            "priority_label": PRIORITY_LABEL.get(t.priority, "medium"),
            "status": t.status,
        }
        for t in tickets
    ]


# ── PUT /support/tickets/{ticket_id}/close ─────────────────────────────────────

@app.put("/support/tickets/{ticket_id}/close")
def close_ticket(ticket_id: str, customer_id: Optional[str] = None, db: Session = Depends(get_db)):
    tid = ticket_id.upper().strip()
    ticket = db.query(Ticket).filter(Ticket.id == tid).first()
    if not ticket:
        return {
            "success": False,
            "data": {},
            "message": f"Ticket {tid} not found.",
        }
    ticket.status = "closed"
    db.commit()
    return {
        "success": True,
        "data": {"ticket_id": ticket.id, "status": "closed"},
        "message": f"Ticket {tid} has been closed. Is there anything else I can help you with?",
    }


# ── PATCH /support/tickets/{ticket_id} ────────────────────────────────────────

class TicketPatch(BaseModel):
    subject:     Optional[str] = None
    description: Optional[str] = None
    status:      Optional[str] = None
    priority:    Optional[int] = None

@app.patch("/support/tickets/{ticket_id}")
def patch_ticket(ticket_id: str, req: TicketPatch, db: Session = Depends(get_db)):
    tid = ticket_id.upper().strip()
    ticket = db.query(Ticket).filter(Ticket.id == tid).first()
    if not ticket:
        return {"success": False, "data": {}, "message": f"Ticket {tid} not found."}
    if req.subject:     ticket.subject     = req.subject
    if req.description: ticket.description = req.description
    if req.status:      ticket.status      = req.status
    if req.priority is not None: ticket.priority = req.priority
    db.commit()
    return {
        "success": True,
        "data": {"ticket_id": tid},
        "message": f"Ticket {tid} updated.",
    }


# ── GET /support/known-issues ──────────────────────────────────────────────────

@app.get("/support/known-issues")
def known_issues(db: Session = Depends(get_db)):
    urgent = db.query(Ticket).filter(
        Ticket.priority.in_([1, 2]),
        Ticket.status == "open"
    ).all()
    issues = [
        {
            "ticket_id": t.id,
            "customer_id": t.customer_id,
            "subject": t.subject,
            "priority": t.priority,
            "priority_label": PRIORITY_LABEL.get(t.priority, "high"),
            "status": t.status,
        }
        for t in urgent
    ]
    if not issues:
        return {"success": True, "data": [], "message": "No known outages or widespread issues at the moment."}
    return {
        "success": True,
        "data": issues,
        "count": len(issues),
        "message": f"There are {len(issues)} active high-priority issue(s) being tracked.",
    }


# ── PUT /support/tickets/{ticket_id}/escalate ──────────────────────────────────

@app.put("/support/tickets/{ticket_id}/escalate")
def escalate_ticket(ticket_id: str, customer_id: Optional[str] = None, db: Session = Depends(get_db)):
    tid = ticket_id.upper().strip()
    ticket = db.query(Ticket).filter(Ticket.id == tid).first()
    if not ticket:
        return {
            "success": False,
            "data": {},
            "message": f"Ticket {tid} not found.",
        }

    ticket.priority = 1   # urgent
    ticket.status = "open"
    db.commit()

    return {
        "success": True,
        "data": {
            "ticket_id": ticket.id,
            "priority": 1,
            "priority_label": "urgent",
            "status": "open",
        },
        "message": (
            f"Ticket {tid} has been escalated to urgent priority. "
            "A senior agent will reach out to you within 24 hours."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Analytics endpoints
# ══════════════════════════════════════════════════════════════════════════════

# In-memory analytics data (no DB needed — metrics are ephemeral by nature)
_METRIC_NAMES = ["page_views", "clicks", "conversions", "bounce_rate", "sessions", "revenue"]
_REGIONS = ["us-east-1", "eu-west-1", "ap-south-1"]


@app.get("/analytics/metrics")
def list_metrics(limit: int = Query(10, ge=1, le=100)):
    """Return simulated analytics metrics — used by AnalyticsConnector."""
    random.seed(42)  # deterministic so repeated calls return consistent data
    records = []
    base_time = datetime.utcnow()
    for i in range(min(limit, 30)):
        name = _METRIC_NAMES[i % len(_METRIC_NAMES)]
        records.append(
            {
                "metric_name": name,
                "value": round(random.uniform(50, 10000), 2),
                "unit": "count" if name != "revenue" else "USD",
                "timestamp": (base_time - timedelta(hours=i)).isoformat() + "Z",
                "tags": {
                    "environment": "production",
                    "region": _REGIONS[i % len(_REGIONS)],
                },
            }
        )
    return records


# ── Health check ───────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "mock-api", "version": "1.0.0"}

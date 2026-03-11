"""
Seed data for the mock API server.
Loaded once at startup if the DB is empty.
"""

from datetime import date, timedelta

today = date.today()


CUSTOMERS = [
    {
        "id": "CUST-001",
        "name": "Alice Sharma",
        "email": "alice@example.com",
        "segment": "Premium",
        "account_since": "2021-03-15",
    },
    {
        "id": "CUST-002",
        "name": "Bob Mehta",
        "email": "bob@example.com",
        "segment": "Standard",
        "account_since": "2022-07-01",
    },
    {
        "id": "CUST-003",
        "name": "Priya Nair",
        "email": "priya@example.com",
        "segment": "Premium",
        "account_since": "2020-11-20",
    },
    {
        "id": "CUST-004",
        "name": "Raj Patel",
        "email": "raj@example.com",
        "segment": "Standard",
        "account_since": "2023-01-10",
    },
    {
        "id": "CUST-005",
        "name": "Sam Iqbal",
        "email": "sam@example.com",
        "segment": "Basic",
        "account_since": "2023-06-05",
    },
]


ORDERS = [
    # CUST-001: Expired milk (food → refund)
    {
        "id": "ORD-1001",
        "customer_id": "CUST-001",
        "status": "Delivered",
        "purchase_date": str(today - timedelta(days=30)),
        "amount": 250.00,
        "delivery_status": "Delivered",
    },
    # CUST-002: Laptop (electronics → exchange)
    {
        "id": "ORD-1002",
        "customer_id": "CUST-002",
        "status": "Delivered",
        "purchase_date": str(today - timedelta(days=60)),
        "amount": 75000.00,
        "delivery_status": "Delivered",
    },
    # CUST-003: Wheat flour (food → refund)
    {
        "id": "ORD-1003",
        "customer_id": "CUST-003",
        "status": "Delivered",
        "purchase_date": str(today - timedelta(days=45)),
        "amount": 150.00,
        "delivery_status": "Delivered",
    },
    # CUST-004: Toaster (appliances → exchange)
    {
        "id": "ORD-1004",
        "customer_id": "CUST-004",
        "status": "Delivered",
        "purchase_date": str(today - timedelta(days=90)),
        "amount": 3500.00,
        "delivery_status": "Delivered",
    },
    # CUST-005: In-transit (not expired yet)
    {
        "id": "ORD-1005",
        "customer_id": "CUST-005",
        "status": "In Transit",
        "purchase_date": str(today - timedelta(days=2)),
        "amount": 1200.00,
        "delivery_status": "In Transit",
    },
    # CUST-001: A second valid order (not expired)
    {
        "id": "ORD-1006",
        "customer_id": "CUST-001",
        "status": "Delivered",
        "purchase_date": str(today - timedelta(days=5)),
        "amount": 899.00,
        "delivery_status": "Delivered",
    },
    # CUST-002: A pharma item (pharma → refund)
    {
        "id": "ORD-1007",
        "customer_id": "CUST-002",
        "status": "Delivered",
        "purchase_date": str(today - timedelta(days=10)),
        "amount": 580.00,
        "delivery_status": "Delivered",
    },
    # CUST-003: A TV (electronics → exchange)
    {
        "id": "ORD-1008",
        "customer_id": "CUST-003",
        "status": "Delivered",
        "purchase_date": str(today - timedelta(days=120)),
        "amount": 45000.00,
        "delivery_status": "Delivered",
    },
]


PRODUCTS = [
    # ORD-1001 — Milk, expired 20 days ago → refund
    {
        "order_id": "ORD-1001",
        "name": "Organic Full Cream Milk",
        "category": "food",
        "expiry_date": str(today - timedelta(days=20)),
        "warranty_months": 0,
    },
    # ORD-1002 — Laptop, expires far future, in-warranty → exchange
    {
        "order_id": "ORD-1002",
        "name": "ProBook Laptop 15-inch",
        "category": "electronics",
        "expiry_date": str(today + timedelta(days=730)),
        "warranty_months": 24,
    },
    # ORD-1003 — Wheat flour, expired 5 days ago → refund
    {
        "order_id": "ORD-1003",
        "name": "Whole Wheat Flour 5kg",
        "category": "food",
        "expiry_date": str(today - timedelta(days=5)),
        "warranty_months": 0,
    },
    # ORD-1004 — Toaster, expired product warranty → exchange
    {
        "order_id": "ORD-1004",
        "name": "Pop-Up Toaster 2-Slice",
        "category": "appliances",
        "expiry_date": str(today + timedelta(days=365)),
        "warranty_months": 12,
    },
    # ORD-1005 — Olive oil, fresh (not expired)
    {
        "order_id": "ORD-1005",
        "name": "Extra Virgin Olive Oil",
        "category": "food",
        "expiry_date": str(today + timedelta(days=180)),
        "warranty_months": 0,
    },
    # ORD-1006 — Headphones, fine
    {
        "order_id": "ORD-1006",
        "name": "Wireless Headphones",
        "category": "electronics",
        "expiry_date": str(today + timedelta(days=900)),
        "warranty_months": 12,
    },
    # ORD-1007 — Cough syrup, expired 2 days ago → refund
    {
        "order_id": "ORD-1007",
        "name": "Cough Syrup 100ml",
        "category": "pharma",
        "expiry_date": str(today - timedelta(days=2)),
        "warranty_months": 0,
    },
    # ORD-1008 — 4K TV, in-warranty → exchange
    {
        "order_id": "ORD-1008",
        "name": "4K Smart TV 55-inch",
        "category": "electronics",
        "expiry_date": str(today + timedelta(days=1500)),
        "warranty_months": 24,
    },
]


TICKETS = [
    {
        "id": "TICK-1001",
        "customer_id": "CUST-001",
        "subject": "WiFi router keeps disconnecting",
        "description": "My router drops connection every 30 minutes.",
        "priority": 2,   # high
        "status": "open",
    },
    {
        "id": "TICK-1002",
        "customer_id": "CUST-002",
        "subject": "Invoice shows wrong amount",
        "description": "My last invoice shows ₹5000 instead of ₹2500.",
        "priority": 3,   # medium
        "status": "pending",
    },
    {
        "id": "TICK-1003",
        "customer_id": "CUST-003",
        "subject": "App crashes on login",
        "description": "The mobile app crashes immediately after I enter my password.",
        "priority": 1,   # urgent
        "status": "open",
    },
    {
        "id": "TICK-1004",
        "customer_id": "CUST-004",
        "subject": "Delivery not received",
        "description": "My order ORD-1004 was marked delivered but I never got it.",
        "priority": 2,   # high
        "status": "open",
    },
    {
        "id": "TICK-1005",
        "customer_id": "CUST-005",
        "subject": "Wrong item delivered",
        "description": "I ordered olive oil but received coconut oil.",
        "priority": 3,   # medium
        "status": "resolved",
    },
]

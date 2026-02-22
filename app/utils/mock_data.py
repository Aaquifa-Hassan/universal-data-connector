import random
from datetime import datetime, timedelta
from typing import List, Dict, Any

def generate_mock_crm_data(count: int = 10) -> List[Dict[str, Any]]:
    data = []
    for i in range(count):
        data.append({
            "customer_id": f"CUST-{i+1:05d}",
            "name": f"Customer {i+1}",
            "email": f"customer{i+1}@example.com",
            "phone": f"+1-555-01{i+1:02d}",
            "company": f"Company {i%5 + 1}",
            "status": random.choice(["active", "inactive", "pending"])
        })
    return data

def generate_mock_support_data(count: int = 10) -> List[Dict[str, Any]]:
    data = []
    for i in range(count):
        data.append({
            "ticket_id": f"TICKET-{i+1:05d}",
            "customer_id": f"CUST-{random.randint(1, 100):05d}",
            "subject": f"Issue {i+1}",
            "description": f"Description for issue {i+1}",
            "priority": random.choice(["low", "normal", "high", "critical"]),
            "status": random.choice(["open", "in_progress", "resolved", "closed"]),
            "created_at": (datetime.now() - timedelta(days=random.randint(0, 30))).isoformat()
        })
    return data

def generate_mock_analytics_data(count: int = 10) -> List[Dict[str, Any]]:
    data = []
    metrics = ["page_views", "clicks", "conversions", "bounce_rate"]
    for i in range(count):
        data.append({
            "metric_name": random.choice(metrics),
            "value": round(random.uniform(10, 1000), 2),
            "unit": "count",
            "timestamp": (datetime.now() - timedelta(hours=random.randint(0, 24))).isoformat(),
            "tags": {"environment": "production", "region": "us-east-1"}
        })
    return data

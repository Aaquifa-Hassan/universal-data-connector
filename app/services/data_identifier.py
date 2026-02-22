
from typing import List, Dict

def identify_data_type(data: List[Dict]) -> str:
    if not data:
        return "empty"
    first_item = data[0]
    if "metric_name" in first_item:
        return "analytics_metrics"
    if "ticket_id" in first_item:
        return "support_tickets"
    if "customer_id" in first_item:
        return "crm_customers"
    return "unknown"

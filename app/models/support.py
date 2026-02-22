from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class Ticket(BaseModel):
    ticket_id: str
    customer_id: str
    subject: str
    description: Optional[str] = None
    priority: str = "normal"
    status: str = "open"
    created_at: datetime = datetime.now()

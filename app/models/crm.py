from pydantic import BaseModel
from typing import Optional

class Customer(BaseModel):
    customer_id: str
    name: str
    email: str
    phone: Optional[str] = None
    company: Optional[str] = None
    status: str = "active"

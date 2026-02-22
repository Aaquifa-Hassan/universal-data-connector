from pydantic import BaseModel
from typing import Dict, Any
from datetime import datetime

class Metric(BaseModel):
    metric_name: str
    value: float
    unit: str
    timestamp: datetime = datetime.now()
    tags: Dict[str, Any] = {}

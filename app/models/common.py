
from pydantic import BaseModel
from typing import Any, List

class Metadata(BaseModel):
    total_results: int
    returned_results: int
    data_freshness: str
    source: str = "unknown"

class DataResponse(BaseModel):
    data: List[Any]
    metadata: Metadata

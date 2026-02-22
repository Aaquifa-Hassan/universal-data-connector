
import json
from app.connectors.base import BaseConnector
from typing import List, Dict, Any
from app.utils.mock_data import generate_mock_crm_data

class CRMConnector(BaseConnector):

    def fetch(self, **kwargs) -> List[Dict[str, Any]]:
        limit = int(kwargs.get("limit", 10))
        return generate_mock_crm_data(count=limit)

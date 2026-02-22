
import json
from app.connectors.base import BaseConnector
from typing import List, Dict, Any
from app.utils.mock_data import generate_mock_analytics_data

class AnalyticsConnector(BaseConnector):
    def fetch(self, **kwargs) -> List[Dict[str, Any]]:
        limit = int(kwargs.get("limit", 10))
        return generate_mock_analytics_data(count=limit)

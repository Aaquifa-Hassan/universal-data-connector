"""Analytics connector — thin sync wrapper around the mock Analytics API."""

import httpx
from app.config import settings


class AnalyticsConnector:
    def fetch(self, limit: int = 10):
        base = getattr(settings, "analytics_api_url", "http://localhost:8001/analytics").rstrip("/")
        try:
            resp = httpx.get(f"{base}/metrics", params={"limit": limit}, timeout=10.0)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return []

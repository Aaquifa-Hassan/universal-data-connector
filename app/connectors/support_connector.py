"""Support connector — thin sync wrapper around the mock Support API."""

import httpx
from app.config import settings


class SupportConnector:
    def fetch(self, limit: int = 10, status: str = None, priority: int = None):
        base = settings.support_api_url.rstrip("/")
        params = {"limit": limit}
        if status:
            params["status"] = status
        if priority is not None:
            params["priority"] = priority
        try:
            resp = httpx.get(f"{base}/tickets", params=params, timeout=10.0)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return []

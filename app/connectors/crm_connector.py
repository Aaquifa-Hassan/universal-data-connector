"""CRM connector — thin sync wrapper around the mock CRM API."""

import httpx
from app.config import settings


class CRMConnector:
    def fetch(self, limit: int = 10):
        base = settings.crm_api_url.rstrip("/")
        try:
            resp = httpx.get(f"{base}/contacts", params={"limit": limit}, timeout=10.0)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return []

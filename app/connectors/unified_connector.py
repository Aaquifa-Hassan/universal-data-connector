"""
UnifiedConnector — async bridge between llm.py and the mock API server.

All methods return a standardised envelope:
    { "success": bool, "data": dict | list, "message": str }

The mock server runs on http://localhost:8001 by default.
Set crm_api_url / support_api_url in .env to override.
"""

import httpx
from typing import Optional

from app.config import settings


class ConfigurationError(Exception):
    """Raised when a required API URL/credential is missing."""


class UnifiedConnector:
    """Single async connector for CRM (Salesforce-like) and Support (Freshdesk-like)."""

    def __init__(self):
        self._crm_base = settings.crm_api_url.rstrip("/")         # e.g. http://localhost:8001/crm
        self._sup_base = settings.support_api_url.rstrip("/")     # e.g. http://localhost:8001/support
        if not self._crm_base or not self._sup_base:
            raise ConfigurationError("crm_api_url or support_api_url not configured in .env")

    # ── internal helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _error(message: str) -> dict:
        return {"success": False, "data": {}, "message": message}

    async def _get(self, url: str, params: dict = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, params=params)
                r.raise_for_status()
                return r.json()
        except httpx.ConnectError:
            return self._error(
                "I'm unable to reach the backend service right now. "
                "Please make sure the mock API server is running on port 8001."
            )
        except httpx.HTTPStatusError as e:
            return self._error(f"API error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            return self._error(f"Unexpected error: {e}")

    async def _post(self, url: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(url, json=payload)
                r.raise_for_status()
                return r.json()
        except httpx.ConnectError:
            return self._error(
                "I'm unable to reach the backend service right now. "
                "Please make sure the mock API server is running on port 8001."
            )
        except httpx.HTTPStatusError as e:
            return self._error(f"API error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            return self._error(f"Unexpected error: {e}")

    async def _put(self, url: str, params: dict = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.put(url, params=params)
                r.raise_for_status()
                return r.json()
        except httpx.ConnectError:
            return self._error(
                "I'm unable to reach the backend service right now. "
                "Please make sure the mock API server is running on port 8001."
            )
        except httpx.HTTPStatusError as e:
            return self._error(f"API error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            return self._error(f"Unexpected error: {e}")

    async def _patch(self, url: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.patch(url, json=payload)
                r.raise_for_status()
                return r.json()
        except httpx.ConnectError:
            return self._error(
                "I'm unable to reach the backend service right now. "
                "Please make sure the mock API server is running on port 8001."
            )
        except httpx.HTTPStatusError as e:
            return self._error(f"API error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            return self._error(f"Unexpected error: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    #  CRM methods
    # ═══════════════════════════════════════════════════════════════════════════

    async def authenticate_user(self, customer_id: str) -> dict:
        """Verify a customer by ID."""
        return await self._post(
            f"{self._crm_base}/authenticate",
            {"customer_id": customer_id},
        )

    async def get_customer_profile(self, customer_id: str) -> dict:
        """Fetch the customer's full profile."""
        return await self._get(f"{self._crm_base}/customers/{customer_id}")

    async def update_customer_profile(self, customer_id: str, **fields) -> dict:
        """Update customer contact details (email, name, segment)."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.put(
                    f"{self._crm_base}/customers/{customer_id}",
                    json=fields,
                )
                r.raise_for_status()
                return r.json()
        except Exception as e:
            return self._error(f"Update failed: {e}")

    async def get_customer_orders(self, customer_id: str, limit: int = 5) -> dict:
        """Fetch list of recent orders for a customer."""
        return await self._get(
            f"{self._crm_base}/customers/{customer_id}/orders",
            params={"limit": limit},
        )

    async def get_order_details(self, customer_id: str, order_id: str) -> dict:
        """
        Fetch order + product details.
        Response includes: expired, recommended_resolution (refund/exchange),
        delivery_status, purchase_date, amount.
        """
        return await self._get(
            f"{self._crm_base}/orders/{order_id}",
            params={"customer_id": customer_id},
        )

    async def initiate_refund(
        self,
        order_id: str,
        customer_id: str,
        reason: Optional[str] = "Customer request",
    ) -> dict:
        """Create a refund case for an order."""
        return await self._post(
            f"{self._crm_base}/refund",
            {"order_id": order_id, "customer_id": customer_id, "reason": reason},
        )

    async def initiate_exchange(
        self,
        order_id: str,
        customer_id: str,
        reason: Optional[str] = "Customer request",
    ) -> dict:
        """Create an exchange case for an order."""
        return await self._post(
            f"{self._crm_base}/exchange",
            {"order_id": order_id, "customer_id": customer_id, "reason": reason},
        )

    async def create_case(
        self,
        customer_id: str,
        subject: str,
        description: str,
        category: str = "generic",
        order_id: Optional[str] = None,
    ) -> dict:
        """Log a generic case (delivery, billing, warranty, etc.)."""
        return await self._post(
            f"{self._crm_base}/cases",
            {
                "customer_id": customer_id,
                "subject": subject,
                "description": description,
                "category": category,
                "order_id": order_id,
            },
        )

    # ═══════════════════════════════════════════════════════════════════════════
    #  Support methods
    # ═══════════════════════════════════════════════════════════════════════════

    async def check_ticket_status(
        self,
        ticket_id: str,
        customer_id: Optional[str] = None,
    ) -> dict:
        """Fetch ticket status + ETA."""
        params = {}
        if customer_id:
            params["customer_id"] = customer_id
        return await self._get(
            f"{self._sup_base}/tickets/{ticket_id}",
            params=params,
        )

    async def raise_support_ticket(
        self,
        customer_id: str,
        subject: str,
        description: str,
        email: Optional[str] = None,
        priority: int = 3,
    ) -> dict:
        """Create a new support ticket."""
        return await self._post(
            f"{self._sup_base}/tickets",
            {
                "customer_id": customer_id,
                "subject": subject,
                "description": description,
                "email": email,
                "priority": priority,
            },
        )

    async def escalate_ticket(
        self,
        ticket_id: str,
        customer_id: Optional[str] = None,
    ) -> dict:
        """Escalate ticket to urgent (priority 1)."""
        params = {}
        if customer_id:
            params["customer_id"] = customer_id
        return await self._put(
            f"{self._sup_base}/tickets/{ticket_id}/escalate",
            params=params,
        )

    async def close_ticket(
        self,
        ticket_id: str,
        customer_id: Optional[str] = None,
    ) -> dict:
        """Close a ticket once resolved."""
        params = {}
        if customer_id:
            params["customer_id"] = customer_id
        return await self._put(
            f"{self._sup_base}/tickets/{ticket_id}/close",
            params=params,
        )

    async def update_ticket(
        self,
        ticket_id: str,
        customer_id: Optional[str] = None,
        **fields,
    ) -> dict:
        """Update ticket fields (subject, description, status, priority)."""
        return await self._patch(
            f"{self._sup_base}/tickets/{ticket_id}",
            fields,
        )

    async def get_known_issues(self) -> dict:
        """Fetch current known high-priority open issues."""
        return await self._get(f"{self._sup_base}/known-issues")

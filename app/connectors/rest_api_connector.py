"""
RestApiConnector — Calls a customer's Data API Gateway over HTTP.

The customer owns the SQL and the datalake credentials.
This connector only knows: base_url + api_key → standardized results.

Registered in UnifiedConnector for datalakes of type "rest_api".
"""

import httpx
import logging
from typing import Any, Dict, Optional

from app.connectors.base import AsyncBaseConnector
from app.services.credentials_manager import credentials_manager

logger = logging.getLogger(__name__)

# How long (seconds) to wait for the customer's API before giving up
_DEFAULT_TIMEOUT = 15.0


class RestApiConnector(AsyncBaseConnector):
    """
    Connector that routes data requests to a customer-hosted REST API,
    instead of directly to a datalake. The customer's API holds all SQL.

    credentials.json entry shape:
    {
      "id":   "acme_corp",
      "type": "rest_api",
      "name": "ACME Corp Gateway",
      "credentials": {
        "base_url":        "https://api.acme.com",
        "api_key":         "sk-acme-xxxxxxxxxxxx",
        "api_version":     "v1",          # optional, defaults to "v1"
        "timeout_seconds": 15             # optional, defaults to 15
      }
    }
    """

    def __init__(self, datalake_id: str):
        self.datalake_id = datalake_id
        creds = credentials_manager.get_credentials(datalake_id) or {}

        self.base_url = creds.get("base_url", "").rstrip("/")
        self.api_key = creds.get("api_key", "")
        self.api_version = creds.get("api_version", "v1")
        self.timeout = float(creds.get("timeout_seconds", _DEFAULT_TIMEOUT))

        if not self.base_url or not self.api_key:
            logger.warning(
                "[REST_API] datalake '%s' is missing base_url or api_key. "
                "All calls will fail until credentials.json is updated.",
                datalake_id,
            )

    # ─────────────────────────────────────────────────────────────────────────
    #  Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        """Build a full URL: base_url/api/v1/<path>"""
        return f"{self.base_url}/api/{self.api_version}/{path.lstrip('/')}"

    def _ok(self, data: Any, message: str = "OK") -> Dict[str, Any]:
        return {"success": True, "data": data, "message": message}

    def _error(self, message: str, status_code: int = 0) -> Dict[str, Any]:
        logger.error("[REST_API][%s] %s (HTTP %s)", self.datalake_id, message, status_code)
        return {"success": False, "data": [], "message": message}

    async def _get(self, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Perform an authenticated GET request and normalize the response."""
        url = self._url(path)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, headers=self._headers, params=params or {})
            return self._handle_response(resp)
        except httpx.TimeoutException:
            return self._error(f"Request to {url} timed out after {self.timeout}s")
        except httpx.RequestError as exc:
            return self._error(f"Network error calling {url}: {exc}")

    def _handle_response(self, resp: httpx.Response) -> Dict[str, Any]:
        """Turn an HTTP response into the standard { success, data, message } envelope."""
        try:
            body = resp.json()
        except Exception:
            body = {"detail": resp.text}

        if resp.status_code == 200:
            # Customer API may return { "data": [...] } or a raw list/dict.
            # Normalize both cases.
            data = body.get("data", body) if isinstance(body, dict) else body
            return self._ok(data, body.get("message", "OK") if isinstance(body, dict) else "OK")

        if resp.status_code == 404:
            return self._error(body.get("message", "Resource not found."), 404)

        if resp.status_code == 401:
            return self._error("Unauthorized — check the api_key in credentials.json.", 401)

        if resp.status_code == 429:
            retry = body.get("retry_after", "?")
            return self._error(f"Rate limited by customer API. Retry after {retry}s.", 429)

        # Catch-all for 5xx and other unexpected codes
        return self._error(
            body.get("message", f"Unexpected response from customer API: HTTP {resp.status_code}"),
            resp.status_code,
        )

    # ─────────────────────────────────────────────────────────────────────────
    #  AsyncBaseConnector interface
    # ─────────────────────────────────────────────────────────────────────────

    async def execute_query(self, query: str, **kwargs) -> Dict[str, Any]:
        """
        Generic fallback required by AsyncBaseConnector.

        For REST API connectors, direct SQL is not supported — the SQL lives
        on the customer's side. Use the named intent methods below instead.

        'query' here is treated as an intent string for diagnostic purposes.
        """
        logger.warning(
            "[REST_API] execute_query() called with raw query on a REST connector. "
            "Use named methods (get_customer, get_orders, etc.) instead. "
            "Returning error."
        )
        return self._error(
            "Raw SQL queries are not supported on REST API connectors. "
            "The customer's API handles SQL internally. "
            f"Intent hint received: {query!r}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    #  Named intent methods — these are what UnifiedConnector calls
    # ─────────────────────────────────────────────────────────────────────────

    async def get_customer(self, customer_id: str) -> Dict[str, Any]:
        """
        Authenticate / look up a customer by ID.
        Maps to: GET /api/v1/customers/{customer_id}
        """
        logger.info("[REST_API][%s] get_customer id=%s", self.datalake_id, customer_id)
        return await self._get(f"customers/{customer_id}")

    async def get_customer_orders(
        self, customer_id: str, limit: int = 5, status: str = "ALL"
    ) -> Dict[str, Any]:
        """
        Fetch recent orders for a customer.
        Maps to: GET /api/v1/customers/{customer_id}/orders?limit=N&status=X
        """
        logger.info(
            "[REST_API][%s] get_customer_orders id=%s limit=%s status=%s",
            self.datalake_id, customer_id, limit, status,
        )
        return await self._get(
            f"customers/{customer_id}/orders",
            params={"limit": limit, "status": status},
        )

    async def get_order_details(self, order_id: str) -> Dict[str, Any]:
        """
        Fetch full order + line items for a given order.
        Maps to: GET /api/v1/orders/{order_id}
        """
        logger.info("[REST_API][%s] get_order_details id=%s", self.datalake_id, order_id)
        return await self._get(f"orders/{order_id}")

    async def get_support_tickets(
        self, customer_id: str, status: str = "OPEN"
    ) -> Dict[str, Any]:
        """
        Fetch support tickets for a customer.
        Maps to: GET /api/v1/customers/{customer_id}/tickets?status=X
        """
        logger.info(
            "[REST_API][%s] get_support_tickets id=%s status=%s",
            self.datalake_id, customer_id, status,
        )
        return await self._get(
            f"customers/{customer_id}/tickets",
            params={"status": status},
        )

    async def health_check(self) -> Dict[str, Any]:
        """
        Ping the customer's gateway health endpoint.
        Maps to: GET /api/v1/health
        """
        return await self._get("health")

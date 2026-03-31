from typing import Optional, Dict, Any, List
import re
import logging

from app.config import settings
from app.connectors.snowflake_connector import SnowflakeConnector
from app.connectors.rest_api_connector import RestApiConnector
from app.services.business_rules import decide_resolution, get_ticket_priority
from app.services.cache import data_cache, make_cache_key
from datetime import date as _date

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Raised when a required API URL/credential is missing."""


class UnifiedConnector:
    """
    Unified Connector — Registry-based system that integrates multiple SQL datalakes.
    Supports generic SQL queries and applies centralized business rules.
    """

    def __init__(self):
        self._connectors: Dict[str, Any] = {}
        self._initialize_connectors()

    def _initialize_connectors(self):
        """Build the registry of connectors based on configured datalakes."""
        for dl in settings.datalakes:
            dl_id = dl["id"]
            dl_type = dl["type"]
            
            if dl_type == "snowflake":
                self._connectors[dl_id] = SnowflakeConnector(dl_id)
            elif dl_type == "rest_api":
                self._connectors[dl_id] = RestApiConnector(dl_id)
                logger.info("[UNIFIED] Registered REST API connector: %s", dl_id)
            # Add other connector types here as needed (e.g., bigquery, postgres)

    def _error(self, message: str) -> dict:
        return {"success": False, "data": {}, "message": message}

    async def execute_query(self, datalake_id: str, query: str) -> Dict[str, Any]:
        """
        Generic entry point to execute a query on any registered SQL datalake.
        Applies business rules to the results if applicable.
        """
        connector = self._connectors.get(datalake_id)
        if not connector:
            return self._error(f"Datalake {datalake_id} not found or not configured.")

        # --- Cache Check ---
        cache_key = make_cache_key("execute_query", datalake_id=datalake_id, query=query)
        cached = data_cache.get(cache_key)
        if cached:
            print(f"[CACHE HIT] query on {datalake_id}")
            return cached

        result = await connector.execute_query(query)
        
        if result.get("success") and isinstance(result.get("data"), list):
            # Apply business rules to rows if they look like orders or products
            enriched_data = self._apply_business_rules(result["data"])
            result["data"] = enriched_data
            
        data_cache.set(cache_key, result)
        return result

    def _apply_business_rules(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Centrally apply business rules to SQL result sets."""
        for row in data:
            # Rule for Orders/Products (Standard SQL columns)
            # Check for common column names used in TPCH or similar schemas
            purchase_date = row.get("purchase_date") or row.get("o_orderdate")
            category = row.get("category") or row.get("p_type")
            
            if category and purchase_date:
                try:
                    days_since = (_date.today() - _date.fromisoformat(str(purchase_date))).days
                except Exception:
                    days_since = 999
                
                rule = decide_resolution(str(category), days_since)
                row["recommended_resolution"] = rule["resolution"]
                row["resolution_reason"] = rule["reason"]
                row["expired"] = days_since > 30

        return data

    # ═══════════════════════════════════════════════════════════════════════════
    #  Convenience Methods (Redirect to generic execute_query)
    # ═══════════════════════════════════════════════════════════════════════════

    async def authenticate_user(self, customer_id: str, datalake_id: str = "snowflake_primary") -> dict:
        """Verify a customer by ID. Routes to REST API or Snowflake depending on connector type."""
        connector = self._connectors.get(datalake_id)

        # ── REST API path (customer owns the SQL) ──────────────────────────────
        if isinstance(connector, RestApiConnector):
            logger.info("[UNIFIED] authenticate_user → REST API [%s] id=%s", datalake_id, customer_id)
            clean_id = re.sub(r'[^0-9]', '', str(customer_id))
            cache_key = make_cache_key("authenticate_user", datalake_id=datalake_id, customer_id=clean_id)
            cached = data_cache.get(cache_key)
            if cached:
                logger.info("[CACHE HIT] authenticate_user %s", clean_id)
                return cached
            resp = await connector.get_customer(clean_id)
            data_cache.set(cache_key, resp)
            return resp

        # ── Snowflake path (direct SQL) ────────────────────────────────────────
        match = re.search(r'(\d+)', str(customer_id))
        ckey = match.group(1) if match else customer_id
        sql = f"SELECT * FROM CUSTOMER WHERE C_CUSTKEY = {ckey}"

        resp = await self.execute_query(datalake_id, sql)
        if resp["success"] and resp["data"]:
            row = resp["data"][0]
            custkey = row.get("c_custkey") or row.get("C_CUSTKEY")
            name    = row.get("c_name")    or row.get("C_NAME")
            profile = {
                "customer_id":     f"CUST-{custkey}",
                "name":            name,
                "address":         row.get("c_address")    or row.get("C_ADDRESS"),
                "nation_key":      row.get("c_nationkey")  or row.get("C_NATIONKEY"),
                "phone":           row.get("c_phone")      or row.get("C_PHONE"),
                "account_balance": row.get("c_acctbal")   or row.get("C_ACCTBAL"),
                "market_segment":  row.get("c_mktsegment") or row.get("C_MKTSEGMENT"),
                "comment":         row.get("c_comment")   or row.get("C_COMMENT"),
            }
            profile = {k: v for k, v in profile.items() if v is not None}
            return {
                "success": True,
                "data": profile,
                "message": f"Successfully authenticated {name} from {datalake_id}."
            }
        return self._error(f"Customer {customer_id} not found in {datalake_id}.")

    async def get_customer_profile(self, customer_id: str, datalake_id: str = "snowflake_primary") -> dict:
        match = re.search(r'(\d+)', str(customer_id))
        ckey = match.group(1) if match else customer_id
        sql = f"SELECT * FROM CUSTOMER WHERE C_CUSTKEY = {ckey}"
        return await self.execute_query(datalake_id, sql)


    async def _query_snowflake(self, query: str, datalake_id: str = "snowflake_primary") -> Dict[str, Any]:
        """Internal helper to query a specific Snowflake datalake."""
        connector = self._connectors.get(datalake_id)
        if not connector:
            return self._error(f"Snowflake datalake {datalake_id} not configured.")
        return await connector.execute_query(query)

    # --- Snowflake-Native Business Helpers for Aria ---


    async def get_customer_orders(self, customer_id: str, limit: int = 5, datalake_id: str = "snowflake_primary") -> Dict[str, Any]:
        """Fetch recent orders. Routes to REST API or Snowflake depending on connector type."""
        connector = self._connectors.get(datalake_id)
        clean_id = re.sub(r'[^0-9]', '', customer_id)

        if isinstance(connector, RestApiConnector):
            logger.info("[UNIFIED] get_customer_orders → REST API [%s] id=%s", datalake_id, clean_id)
            cache_key = make_cache_key("get_customer_orders", datalake_id=datalake_id, customer_id=clean_id, limit=limit)
            cached = data_cache.get(cache_key)
            if cached:
                return cached
            resp = await connector.get_customer_orders(clean_id, limit=limit)
            data_cache.set(cache_key, resp)
            return resp

        query = f"SELECT * FROM ORDERS WHERE O_CUSTKEY = {clean_id} ORDER BY O_ORDERDATE DESC LIMIT {limit}"
        return await self._query_snowflake(query, datalake_id)

    async def get_order_details(self, order_id: str, datalake_id: str = "snowflake_primary") -> Dict[str, Any]:
        """Fetch order + line items. Routes to REST API or Snowflake depending on connector type."""
        connector = self._connectors.get(datalake_id)
        clean_id = re.sub(r'[^0-9]', '', order_id)

        if isinstance(connector, RestApiConnector):
            logger.info("[UNIFIED] get_order_details → REST API [%s] id=%s", datalake_id, clean_id)
            cache_key = make_cache_key("get_order_details", datalake_id=datalake_id, order_id=clean_id)
            cached = data_cache.get(cache_key)
            if cached:
                return cached
            resp = await connector.get_order_details(clean_id)
            data_cache.set(cache_key, resp)
            return resp

        clean_id = re.sub(r'[^0-9]', '', order_id)
        order_query = f"SELECT * FROM ORDERS WHERE O_ORDERKEY = {clean_id}"
        items_query = f"SELECT * FROM LINEITEM WHERE L_ORDERKEY = {clean_id}"
        ord_res = await self._query_snowflake(order_query, datalake_id)
        item_res = await self._query_snowflake(items_query, datalake_id)
        if ord_res.get("success") and ord_res.get("data"):
            data = {"order": ord_res["data"][0], "items": item_res.get("data", [])}
            return {"success": True, "data": data}
        return {"success": False, "message": "Order not found."}

    async def initiate_refund(self, order_id: str, customer_id: str, reason: str = "Not specified") -> Dict[str, Any]:
        """Simulate a refund and invalidate relevant caches."""
        # 1. Invalidate specific order details cache
        order_key = make_cache_key("get_order_details", order_id=order_id)
        data_cache.invalidate(order_key)
        
        # 2. Invalidate customer orders cache (assumes limit=5 as used in llm.py)
        list_key = make_cache_key("get_customer_orders", customer_id=customer_id, limit=5)
        data_cache.invalidate(list_key)
        
        print(f"[CACHE] Invalidated keys for order {order_id} and customer {customer_id}")
        return {
            "success": True, 
            "message": f"Refund initiated for order {order_id}. Reason: {reason}. Status will update in Snowflake within 24h."
        }

    async def initiate_exchange(self, order_id: str, customer_id: str, item_id: str, reason: str) -> Dict[str, Any]:
        """Simulate an exchange and invalidate relevant caches."""
        order_key = make_cache_key("get_order_details", order_id=order_id)
        data_cache.invalidate(order_key)
        
        list_key = make_cache_key("get_customer_orders", customer_id=customer_id, limit=5)
        data_cache.invalidate(list_key)
        
        return {
            "success": True, 
            "message": f"Exchange requested for item {item_id} in {order_id}. Your order list has been refreshed."
        }

    # --- Snowflake Metadata/Schema Helpers ---

    async def get_table_schema(self, table_name: str, datalake_id: str = "snowflake_primary") -> Dict[str, Any]:
        connector = self._connectors.get(datalake_id)
        if not connector: return self._error(f"Datalake {datalake_id} not configured.")
        return await connector.get_table_schema(table_name)

    async def get_all_schemas(self, datalake_id: str = "snowflake_primary") -> Dict[str, Any]:
        connector = self._connectors.get(datalake_id)
        if not connector: return self._error(f"Datalake {datalake_id} not configured.")
        return await connector.get_all_schemas()

    async def list_snowflake_tables(self, datalake_id: str = "snowflake_primary") -> Dict[str, Any]:
        res = await self.get_all_schemas(datalake_id)
        if res.get("success"):
            tables = sorted(list(set(row["table_name"] for row in res["data"])))
            return {"success": True, "data": tables}
        return res

    async def preview_snowflake_table(self, table_name: str, limit: int = 5, datalake_id: str = "snowflake_primary") -> Dict[str, Any]:
        query = f"SELECT * FROM {table_name} LIMIT {limit}"
        return await self._query_snowflake(query, datalake_id)

    async def query_snowflake(self, query: str, datalake_id: str = "snowflake_primary") -> Dict[str, Any]:
        return await self._query_snowflake(query, datalake_id)

unified_connector = UnifiedConnector()

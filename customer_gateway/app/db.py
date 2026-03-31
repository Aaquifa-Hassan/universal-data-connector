"""
Snowflake connector for the Customer Data API Gateway.

THIS FILE is the only place where:
  - Snowflake credentials are used
  - SQL queries are written

Nothing outside this file ever touches the DB directly.
"""
import asyncio
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

import snowflake.connector

from app.config import settings

logger = logging.getLogger(__name__)


class GatewaySnowflakeConnector:
    """
    Thin async wrapper around snowflake.connector.
    Manages a single reusable connection for the lifetime of the process.
    """

    def __init__(self):
        self._conn = None

    def _get_connection(self):
        if self._conn is not None:
            try:
                self._conn.cursor().execute("SELECT 1")
                return self._conn
            except Exception:
                self._conn = None

        logger.info("[GATEWAY-SF] Opening new Snowflake connection...")
        self._conn = snowflake.connector.connect(
            account=settings.SNOWFLAKE_ACCOUNT,
            user=settings.SNOWFLAKE_USER,
            password=settings.SNOWFLAKE_PASSWORD,
            role=settings.SNOWFLAKE_ROLE,
            warehouse=settings.SNOWFLAKE_WAREHOUSE,
            database=settings.SNOWFLAKE_DATABASE,
            schema=settings.SNOWFLAKE_SCHEMA,
        )
        return self._conn

    def _run_query(self, sql: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        """Synchronous: execute SQL, return list of dicts."""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
            if not cur.description:
                return []
            columns = [col[0].lower() for col in cur.description]
            rows = []
            for raw in cur.fetchall():
                row = {}
                for col, val in zip(columns, raw):
                    # Ensure JSON-serialisable types
                    if hasattr(val, "isoformat"):
                        val = val.isoformat()
                    elif isinstance(val, Decimal):
                        val = float(val)
                    row[col] = val
                rows.append(row)
            return rows
        finally:
            cur.close()

    async def query(self, sql: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        """Run a blocking Snowflake query in a thread pool, return list of dicts."""
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, self._run_query, sql, params)
        except Exception as exc:
            logger.error("[GATEWAY-SF] Query failed: %s", exc)
            raise

    # ─────────────────────────────────────────────────────────────────────────
    #  Named query methods — ALL SQL lives here
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_customer(self, customer_id: str) -> Optional[Dict[str, Any]]:
        """
        SQL: SELECT a single customer row by primary key.
        Parameterised to prevent SQL injection.
        """
        sql = """
            SELECT
                C_CUSTKEY    AS customer_id,
                C_NAME       AS name,
                C_ADDRESS    AS address,
                C_NATIONKEY  AS nation_key,
                C_PHONE      AS phone,
                C_ACCTBAL    AS account_balance,
                C_MKTSEGMENT AS market_segment,
                C_COMMENT    AS comment
            FROM CUSTOMER
            WHERE C_CUSTKEY = %s
        """
        rows = await self.query(sql, (int(customer_id),))
        return rows[0] if rows else None

    async def fetch_customer_orders(
        self, customer_id: str, limit: int = 5, status: str = "ALL"
    ) -> List[Dict[str, Any]]:
        """
        SQL: Fetch recent orders for a customer, with optional status filter.
        """
        if status.upper() == "ALL":
            sql = """
                SELECT
                    O_ORDERKEY   AS order_id,
                    O_CUSTKEY    AS customer_id,
                    O_ORDERSTATUS AS status,
                    O_TOTALPRICE  AS total_price,
                    O_ORDERDATE   AS order_date,
                    O_ORDERPRIORITY AS priority
                FROM ORDERS
                WHERE O_CUSTKEY = %s
                ORDER BY O_ORDERDATE DESC
                LIMIT %s
            """
            return await self.query(sql, (int(customer_id), limit))
        else:
            sql = """
                SELECT
                    O_ORDERKEY    AS order_id,
                    O_CUSTKEY     AS customer_id,
                    O_ORDERSTATUS AS status,
                    O_TOTALPRICE  AS total_price,
                    O_ORDERDATE   AS order_date,
                    O_ORDERPRIORITY AS priority
                FROM ORDERS
                WHERE O_CUSTKEY = %s AND O_ORDERSTATUS = %s
                ORDER BY O_ORDERDATE DESC
                LIMIT %s
            """
            return await self.query(sql, (int(customer_id), status.upper(), limit))

    async def fetch_order_with_items(self, order_id: str) -> Dict[str, Any]:
        """
        SQL: Fetch order header + all line items for a given order key.
        Returns { "order": {...}, "line_items": [...] }
        """
        order_sql = """
            SELECT
                O_ORDERKEY      AS order_id,
                O_CUSTKEY       AS customer_id,
                O_ORDERSTATUS   AS status,
                O_TOTALPRICE    AS total_price,
                O_ORDERDATE     AS order_date,
                O_ORDERPRIORITY AS priority,
                O_COMMENT       AS comment
            FROM ORDERS
            WHERE O_ORDERKEY = %s
        """
        items_sql = """
            SELECT
                L_LINENUMBER  AS item_id,
                L_PARTKEY     AS product_name,
                L_QUANTITY    AS quantity,
                L_EXTENDEDPRICE AS unit_price,
                L_RETURNFLAG  AS return_flag,
                L_LINESTATUS  AS line_status
            FROM LINEITEM
            WHERE L_ORDERKEY = %s
            ORDER BY L_LINENUMBER
        """
        orders = await self.query(order_sql, (int(order_id),))
        items  = await self.query(items_sql, (int(order_id),))
        return {
            "order":      orders[0] if orders else {},
            "line_items": items,
        }

    async def fetch_customer_tickets(
        self, customer_id: str, status: str = "OPEN"
    ) -> List[Dict[str, Any]]:
        """
        SQL: Fetch support tickets.
        NOTE: Replace this with your actual support ticket table name.
        """
        if status.upper() == "ALL":
            sql = """
                SELECT
                    TICKET_ID    AS ticket_id,
                    SUBJECT      AS subject,
                    STATUS       AS status,
                    PRIORITY     AS priority,
                    CREATED_AT   AS created_at
                FROM SUPPORT_TICKETS
                WHERE CUSTOMER_ID = %s
                ORDER BY CREATED_AT DESC
            """
            return await self.query(sql, (int(customer_id),))
        else:
            sql = """
                SELECT
                    TICKET_ID    AS ticket_id,
                    SUBJECT      AS subject,
                    STATUS       AS status,
                    PRIORITY     AS priority,
                    CREATED_AT   AS created_at
                FROM SUPPORT_TICKETS
                WHERE CUSTOMER_ID = %s AND STATUS = %s
                ORDER BY CREATED_AT DESC
            """
            return await self.query(sql, (int(customer_id), status.upper()))


# Module-level singleton — one connection reused across the app lifecycle
sf = GatewaySnowflakeConnector()

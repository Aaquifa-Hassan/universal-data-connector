
import snowflake.connector
import asyncio
import concurrent.futures
from typing import List, Dict, Any, Optional
from app.connectors.base import AsyncBaseConnector
from app.services.credentials_manager import credentials_manager

class SnowflakeConnector(AsyncBaseConnector):
    """Connector for executing queries on Snowflake."""

    def __init__(self, datalake_id: str = "snowflake_sample"):
        self.datalake_id = datalake_id
        self.creds = credentials_manager.get_credentials(datalake_id) or {}
        self._conn = None

    def _error(self, message: str) -> dict:
        return {"success": False, "data": [], "message": message}

    def _get_connection(self):
        if self._conn is not None:
            try:
                # Test connection is alive
                self._conn.cursor().execute("SELECT 1")
                return self._conn
            except Exception:
                self._conn = None

        if not self.creds:
            raise Exception(f"No credentials found for datalake {self.datalake_id}")

        print(f"[SNOWFLAKE] Establishing new connection to {self.datalake_id}...")
        self._conn = snowflake.connector.connect(
            user=self.creds.get("user"),
            password=self.creds.get("password"),
            account=self.creds.get("account"),
            role=self.creds.get("role"),
            warehouse=self.creds.get("warehouse"),
            database=self.creds.get("database"),
            schema=self.creds.get("schema")
        )
        return self._conn

    async def execute_query(self, query: str, **kwargs) -> Dict[str, Any]:
        """Execute a raw SQL query on Snowflake (async-wrapped with connection reuse)."""

        def _run_query():
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(query)
                
                # Fetch results and column names
                if cursor.description:
                    columns = [col[0] for col in cursor.description]
                    raw_results = cursor.fetchall()

                    # Process results to ensure JSON serializability (dates, decimals, etc.)
                    import datetime as _dt
                    from decimal import Decimal as _Decimal
                    results = []
                    for row in raw_results:
                        processed_row = {}
                        for col, val in zip(columns, row):
                            if isinstance(val, (_dt.datetime, _dt.date)):
                                val = val.isoformat()
                            elif isinstance(val, _Decimal):
                                val = float(val)
                            processed_row[col.lower()] = val
                        results.append(processed_row)
                else:
                    results = []

                cursor.close()
                return {"success": True, "data": results, "message": f"Successfully executed query. Found {len(results)} rows."}
            except Exception as e:
                return self._error(f"Snowflake error: {str(e)}")

        # Run the synchronous snowflake call in a thread pool
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _run_query)

    async def list_tables(self) -> dict:
        """List available tables in the configured schema."""
        db = self.creds.get("database")
        schema = self.creds.get("schema")
        return await self.execute_query(f"SHOW TABLES IN SCHEMA {db}.{schema}")

    async def get_table_preview(self, table_name: str, limit: int = 5) -> dict:
        """Get a preview of the data in a specific table."""
        return await self.execute_query(f"SELECT * FROM {table_name} LIMIT {limit}")
    async def get_table_schema(self, table_name: str) -> dict:
        """Fetch column names, types, and comments for a specific table."""
        db = self.creds.get("database")
        schema = self.creds.get("schema")
        # Querying information_schema for portable metadata
        sql = f"""
            SELECT column_name, data_type, comment 
            FROM {db}.information_schema.columns 
            WHERE table_name = '{table_name.upper()}' 
            AND table_schema = '{schema.upper()}'
            ORDER BY ordinal_position
        """
        return await self.execute_query(sql)

    async def get_all_schemas(self) -> dict:
        """Fetch schemas for all tables in the configured database/schema."""
        db = self.creds.get("database")
        schema = self.creds.get("schema")
        sql = f"""
            SELECT table_name, column_name, data_type, comment 
            FROM {db}.information_schema.columns 
            WHERE table_schema = '{schema.upper()}'
            ORDER BY table_name, ordinal_position
        """
        return await self.execute_query(sql)

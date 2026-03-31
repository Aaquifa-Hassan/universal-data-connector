
import asyncio
import json
from app.connectors.unified_connector import UnifiedConnector

async def verify():
    unified = UnifiedConnector()
    
    print("--- Testing Primary Snowflake Datalake ---")
    query = "SELECT C_CUSTKEY, C_NAME FROM CUSTOMER LIMIT 2"
    resp = await unified.execute_query("snowflake_primary", query)
    print(json.dumps(resp, indent=2))
    
    print("\n--- Testing REST API Datalake (ACME Corp Gateway @ 8081) ---")
    # This will call GET /api/v1/customers/1/orders via the gateway
    resp = await unified.get_customer_orders("1", limit=2, datalake_id="acme_corp")
    print(json.dumps(resp, indent=2))
    
    print("\n--- Testing Authentication via Unified Interface ---")
    # This maps to GET /api/v1/customers/1 on the gateway
    auth_resp = await unified.authenticate_user("1", datalake_id="acme_corp")
    print(json.dumps(auth_resp, indent=2))
    
    print("\n--- Verification of Business Rules (Snowflake) ---")
    query_orders = "SELECT O_ORDERKEY as order_id, O_ORDERDATE as purchase_date, 'electronics' as category FROM ORDERS LIMIT 1"
    resp = await unified.execute_query("snowflake_primary", query_orders)
    print(json.dumps(resp, indent=2))

if __name__ == "__main__":
    asyncio.run(verify())

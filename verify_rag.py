import asyncio
import json
from app.services.metadata_service import metadata_service

async def verify_rag():
    print("--- Verifying RAG Schema Retrieval ---")
    
    # Test 1: Semantic query (no direct keywords)
    print("\n[Query: 'Where is my money going?']")
    context = await metadata_service.get_context_for_query("Where is my money going?")
    print(context)
    
    # Test 2: Semantic query (related terms)
    print("\n[Query: 'Who is buying our products?']")
    context = await metadata_service.get_context_for_query("Who is buying our products?")
    print(context)

    print("\n--- RAG Integration Logic Check ---")
    # Verify MetadataService is working correctly with UnifiedConnector
    from app.connectors.unified_connector import UnifiedConnector
    unified = UnifiedConnector()
    schemas = await unified.get_all_schemas()
    if schemas.get("success"):
        print(f"Successfully retrieved {len(schemas['data'])} metadata rows from Snowflake.")
    else:
        print(f"Error fetching metadata: {schemas.get('message')}")

if __name__ == "__main__":
    asyncio.run(verify_rag())

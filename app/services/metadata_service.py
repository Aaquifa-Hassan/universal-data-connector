from typing import List, Dict, Any, Optional
import json
from groq import Groq
from app.config import settings
from app.connectors.unified_connector import UnifiedConnector
from app.services.cache import data_cache, make_cache_key

class MetadataService:
    """Manages datalake schemas and provides context for RAG."""

    def __init__(self):
        self.unified = UnifiedConnector()
        self.client = Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None
        self.model = "llama-3.1-8b-instant"

    async def get_context_for_query(self, user_query: str, datalake_id: str = "snowflake_primary") -> str:
        """
        Retrieve relevant table schemas using LLM-based semantic routing.
        """
        cache_key = f"schemas:{datalake_id}"
        cached_schemas = data_cache.get(cache_key)
        if cached_schemas:
            print(f"[METADATA SERVICE] Cache HIT for schemas: {datalake_id}")
            data = cached_schemas
        else:
            print(f"[METADATA SERVICE] Cache MISS for schemas: {datalake_id}")
            schemas = await self.unified.get_all_schemas(datalake_id)
            if not schemas.get("success"):
                return "No schema information available."
            data = schemas.get("data", [])
            if data:
                data_cache.set(cache_key, data, ttl=3600)  # Schemas change rarely, cache for 1h
            else:
                return "No tables found in the datalake."

        # Collect unique tables and their simple descriptions (only names for routing)
        unique_tables = sorted(list(set(row["table_name"] for row in data)))

        if not self.client:
            # Fallback to keyword matching if no API key
            relevant_tables = [t for t in unique_tables if any(k in t.lower() for k in user_query.lower().split())]
            if not relevant_tables: relevant_tables = unique_tables[:2]
        else:
            # --- Semantic Routing via Llama 3.1 (Groq) with caching ---
            routing_cache_key = make_cache_key("routing", query=user_query, tables=unique_tables)
            cached_routing = data_cache.get(routing_cache_key)
            if cached_routing:
                print(f"[METADATA SERVICE] Cache HIT for routing: {user_query}")
                relevant_tables = cached_routing
            else:
                print(f"[METADATA SERVICE] Cache MISS for routing: {user_query}")
                try:
                    # Ask Llama to pick the top 2 relevant tables
                    prompt = f"""
                    Given these Snowflake table names: {', '.join(unique_tables)}
                    Which 1-2 tables are most relevant to answer this user query: "{user_query}"?
                    Return ONLY a JSON list of table names. Example: ["TABLE1", "TABLE2"]
                    """
                    
                    chat_completion = self.client.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model=self.model,
                        temperature=0.0,
                        max_tokens=50
                    )
                    response_text = chat_completion.choices[0].message.content
                    # Extract JSON list using regex in case of narration
                    import re
                    match = re.search(r'(\[.*\])', response_text)
                    if match:
                        relevant_tables = json.loads(match.group(1))
                        data_cache.set(routing_cache_key, relevant_tables, ttl=600) # Cache routing for 10 mins
                    else:
                        relevant_tables = unique_tables[:2]
                except Exception as e:
                    print(f"[METADATA SERVICE] Routing error: {e}")
                    relevant_tables = unique_tables[:2]

        context = "Here are the relevant table schemas from your Snowflake datalake:\n\n"
        for table in relevant_tables:
            # Case-insensitive match for the table name returned by LLM
            table = str(table).upper()
            context += f"Table: {table}\n"
            cols = [r for r in data if r.get("table_name") == table]
            for c in cols:
                comment = f" -- {c['comment']}" if c.get("comment") else ""
                context += f"  - {c['column_name']} ({c['data_type']}){comment}\n"
            context += "\n"

        return context

        context = "Here are the relevant table schemas from your Snowflake datalake:\n\n"
        for table in relevant_tables:
            context += f"Table: {table}\n"
            cols = [r for r in data if r.get("table_name") == table]
            for c in cols:
                comment = f" -- {c['comment']}" if c.get("comment") else ""
                context += f"  - {c['column_name']} ({c['data_type']}){comment}\n"
            context += "\n"

        return context

metadata_service = MetadataService()

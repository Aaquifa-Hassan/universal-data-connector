from fastapi import Security, HTTPException, status, Query
from fastapi.security.api_key import APIKeyHeader
from app.config import settings
from typing import Optional

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def get_api_key(
    api_key_header: str = Security(api_key_header),
    api_key_query: Optional[str] = Query(None, alias="api_key")
):
    if api_key_header == settings.API_KEY:
        return api_key_header
    if api_key_query == settings.API_KEY:
        return api_key_query
        
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API Key",
    )

"""
Cache management endpoints.
Provides stats, invalidation, and flush operations for the data cache.
"""

from fastapi import APIRouter, Depends
from app.auth import get_api_key
from app.services.cache import data_cache

router = APIRouter(prefix="/cache", tags=["cache"], dependencies=[Depends(get_api_key)])


@router.get("/stats")
def cache_stats():
    """Return cache hit/miss statistics and entry count."""
    return data_cache.stats()


@router.get("/keys")
def cache_keys():
    """List all active cache keys."""
    return {"keys": data_cache.keys()}


@router.delete("/")
def flush_cache():
    """Flush the entire cache."""
    removed = data_cache.clear()
    return {"message": f"Cache flushed. {removed} entries removed."}


@router.delete("/{key}")
def invalidate_key(key: str):
    """Invalidate a specific cache key."""
    found = data_cache.invalidate(key)
    if found:
        return {"message": f"Key '{key}' invalidated."}
    return {"message": f"Key '{key}' not found in cache."}

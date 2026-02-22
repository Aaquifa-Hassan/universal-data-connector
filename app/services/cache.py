"""
In-memory TTL cache service.
Thread-safe cache with configurable TTL for caching connector data.
"""

import time
import hashlib
import json
import threading
from typing import Any, Optional, Dict


class TTLCache:
    """Thread-safe in-memory cache with per-key TTL expiration."""

    def __init__(self, default_ttl: int = 300):
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._default_ttl = default_ttl
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        """Get a value from the cache. Returns None if expired or missing."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if time.time() > entry["expires_at"]:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return entry["value"]

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store a value in the cache with optional custom TTL."""
        with self._lock:
            self._store[key] = {
                "value": value,
                "expires_at": time.time() + (ttl or self._default_ttl),
                "created_at": time.time(),
            }

    def invalidate(self, key: str) -> bool:
        """Remove a specific key from the cache. Returns True if key existed."""
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def clear(self) -> int:
        """Flush the entire cache. Returns number of entries removed."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            self._hits = 0
            self._misses = 0
            return count

    def stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            # Clean expired entries first
            now = time.time()
            expired = [k for k, v in self._store.items() if now > v["expires_at"]]
            for k in expired:
                del self._store[k]

            total = self._hits + self._misses
            return {
                "total_entries": len(self._store),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 2) if total > 0 else 0.0,
                "default_ttl_seconds": self._default_ttl,
            }

    def keys(self):
        """Return list of active (non-expired) cache keys."""
        with self._lock:
            now = time.time()
            return [k for k, v in self._store.items() if now <= v["expires_at"]]


def make_cache_key(source: str, **params) -> str:
    """Generate a deterministic cache key from source + params."""
    filtered = {k: v for k, v in sorted(params.items()) if v is not None}
    raw = f"{source}:{json.dumps(filtered, sort_keys=True)}"
    return hashlib.md5(raw.encode()).hexdigest()


# Global cache instance
data_cache = TTLCache(default_ttl=300)

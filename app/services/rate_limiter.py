"""
Rate limiting service using slowapi.
Provides per-source rate limits for different data connectors.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Per-source rate limit tiers
SOURCE_RATE_LIMITS = {
    "crm": "30/minute",
    "support": "30/minute",
    "analytics": "60/minute",
    "students": "20/minute",
}

DEFAULT_RATE_LIMIT = "30/minute"

# Create the limiter instance (uses in-memory storage by default)
limiter = Limiter(key_func=get_remote_address)


def get_source_limit(source: str) -> str:
    """Get the rate limit string for a given data source."""
    return SOURCE_RATE_LIMITS.get(source, DEFAULT_RATE_LIMIT)

"""
API Key authentication dependency for the Customer Data API Gateway.

Every incoming request from the Universal Data Connector must include:
    Authorization: Bearer <GATEWAY_API_KEY>

The key is configured via the GATEWAY_API_KEY environment variable.
"""
from fastapi import Security, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings

_bearer = HTTPBearer(auto_error=True)


def require_api_key(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    """
    FastAPI dependency — validates the Bearer token on every protected endpoint.
    Returns the token string if valid, raises 401 otherwise.
    """
    token = credentials.credentials
    if token != settings.GATEWAY_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "UNAUTHORIZED",
                "message": "Invalid or missing API key.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token

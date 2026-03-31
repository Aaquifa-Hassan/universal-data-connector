from fastapi import APIRouter
from app.db import sf

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health():
    """
    Public liveness probe — no auth required.
    The Universal Data Connector pings this before each session.
    """
    try:
        # Light query to verify Snowflake connection is alive
        await sf.query("SELECT CURRENT_TIMESTAMP()")
        datalake_status = "connected"
    except Exception as exc:
        datalake_status = f"error: {exc}"

    return {
        "status": "ok",
        "datalake": datalake_status,
        "version": "1.0.0",
    }

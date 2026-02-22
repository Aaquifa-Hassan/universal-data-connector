"""
SSE streaming router.
Streams data source records as Server-Sent Events for large datasets.
"""

import json
import asyncio
from fastapi import APIRouter, Query, Request, Depends
from fastapi.responses import StreamingResponse
from app.connectors.crm_connector import CRMConnector
from app.connectors.support_connector import SupportConnector
from app.connectors.analytics_connector import AnalyticsConnector
from app.auth import get_api_key
from app.services.rate_limiter import limiter

router = APIRouter(prefix="/stream", tags=["streaming"], dependencies=[Depends(get_api_key)])


def _get_connector(source: str):
    """Get the appropriate connector for a data source."""
    connector_map = {
        "crm": CRMConnector(),
        "support": SupportConnector(),
        "analytics": AnalyticsConnector(),
    }
    return connector_map.get(source)


def _sse_event(data: dict, event: str = "record") -> str:
    """Format a dict as an SSE event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _generate_stream(source: str, limit: int, delay: float):
    """Generator that yields SSE events for each record."""
    import time

    if source == "students":
        from app.connectors.student_connector import StudentConnector
        connector = StudentConnector()
        records = connector.fetch(limit=limit)
    else:
        connector = _get_connector(source)
        if not connector:
            yield _sse_event({"error": f"Unknown source: {source}"}, event="error")
            return
        records = connector.fetch(limit=limit)

    total = len(records)

    # Stream start event
    yield _sse_event({"source": source, "total_records": total}, event="start")

    # Stream each record with a small delay to demonstrate streaming
    for i, record in enumerate(records):
        record["_index"] = i + 1
        record["_of"] = total
        yield _sse_event(record, event="record")
        if delay > 0:
            time.sleep(delay)

    # Stream done event
    yield _sse_event({
        "source": source,
        "records_sent": total,
        "status": "complete"
    }, event="done")


@router.get("/{source}")
@limiter.limit("30/minute")
def stream_data(
    request: Request,
    source: str,
    limit: int = Query(50, description="Maximum records to stream"),
    delay: float = Query(0.1, description="Delay between events in seconds (for demo)"),
):
    """
    Stream data from a source as Server-Sent Events (SSE).
    
    Each record is sent as a separate SSE event, making this ideal
    for large datasets where you don't want to wait for the full response.
    
    Events:
    - `start`: Metadata about the stream
    - `record`: Individual data record
    - `done`: Stream completion summary
    """
    return StreamingResponse(
        _generate_stream(source, limit, delay),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


from fastapi import APIRouter, Query, Depends, Request, Response
from app.connectors.crm_connector import CRMConnector
from app.connectors.support_connector import SupportConnector
from app.connectors.analytics_connector import AnalyticsConnector
from app.services.business_rules import apply_voice_limits
from app.services.voice_optimizer import summarize_if_large
from app.services.data_identifier import identify_data_type
from app.services.cache import data_cache, make_cache_key
from app.services.rate_limiter import limiter, get_source_limit
from app.models.common import DataResponse, Metadata
from datetime import datetime
from app.auth import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])


@router.get("/data/{source}", response_model=DataResponse)
@limiter.limit(lambda: "60/minute")  # default, overridden dynamically below
def get_data(request: Request, response: Response, source: str, limit: int = Query(10)):
    # Dynamic rate limit is handled by slowapi decorator above
    connector_map = {
        "crm": CRMConnector(),
        "support": SupportConnector(),
        "analytics": AnalyticsConnector(),
    }

    connector = connector_map.get(source)
    if not connector:
        return {"data": [], "metadata": {"total_results": 0, "returned_results": 0, "data_freshness": "unknown"}}

    # --- Cache layer ---
    cache_key = make_cache_key(source, limit=limit)
    cached = data_cache.get(cache_key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        response.headers["X-Cache-Key"] = cache_key
        return cached

    response.headers["X-Cache"] = "MISS"
    response.headers["X-Cache-Key"] = cache_key

    raw_data = connector.fetch(limit=limit)
    total = len(raw_data)

    filtered = raw_data  # Removed apply_voice_limits to support fetch-all via limit param
    optimized = summarize_if_large(filtered)

    data_type = identify_data_type(raw_data)

    metadata = Metadata(
        total_results=total,
        returned_results=len(optimized),
        data_freshness=f"Data as of {datetime.utcnow().isoformat()}",
    )

    result = DataResponse(data=optimized, metadata=metadata)
    data_cache.set(cache_key, result)

    # Dispatch webhook in background
    try:
        from app.services.webhook_manager import webhook_manager
        import threading
        threading.Thread(
            target=webhook_manager.dispatch,
            args=("data.queried", source, {"source": source, "total_results": total, "returned_results": len(optimized)}),
            daemon=True,
        ).start()
    except Exception:
        pass  # Webhook dispatch is best-effort

    return result


@router.get("/students", response_model=DataResponse)
@limiter.limit("20/minute")
def get_students(
    request: Request,
    response: Response,
    account_id: str = Query(None, description="Filter by student account ID"),
    course_code: str = Query(None, description="Filter by course code"),
    batch: str = Query(None, description="Filter by student batch"),
    term: str = Query(None, description="Filter by term code"),
    min_marks: int = Query(None, description="Minimum marks filter"),
    limit: int = Query(10, description="Maximum number of records")
):
    from app.connectors.student_connector import StudentConnector

    # --- Cache layer ---
    cache_key = make_cache_key("students", account_id=account_id, course_code=course_code,
                                batch=batch, term=term, min_marks=min_marks, limit=limit)
    cached = data_cache.get(cache_key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        response.headers["X-Cache-Key"] = cache_key
        return cached

    response.headers["X-Cache"] = "MISS"
    response.headers["X-Cache-Key"] = cache_key

    connector = StudentConnector()

    # Build filter kwargs
    filters = {
        'account_id': account_id,
        'course_code': course_code,
        'batch': batch,
        'term': term,
        'min_marks': min_marks,
        'limit': limit
    }

    raw_data = connector.fetch(**filters)
    total = len(raw_data)

    metadata = Metadata(
        total_results=total,
        returned_results=total,
        data_freshness=f"Data as of {datetime.utcnow().isoformat()}",
        source="student_database"
    )

    result = DataResponse(data=raw_data, metadata=metadata)
    data_cache.set(cache_key, result)

    return result


from fastapi import APIRouter, Query, Depends
from fastapi.responses import StreamingResponse
from app.connectors.crm_connector import CRMConnector
from app.connectors.support_connector import SupportConnector
from app.connectors.analytics_connector import AnalyticsConnector
from app.auth import get_api_key
import pandas as pd
import io

router = APIRouter(prefix="/export", dependencies=[Depends(get_api_key)])


def _get_data(source: str, **filters):
    """Fetch data from the specified source with optional filters."""
    if source == "students":
        from app.connectors.student_connector import StudentConnector
        return StudentConnector().fetch(**filters)

    connector_map = {
        "crm": CRMConnector(),
        "support": SupportConnector(),
        "analytics": AnalyticsConnector(),
    }
    connector = connector_map.get(source)
    if not connector:
        return []
    return connector.fetch()


@router.get("/{source}")
def export_data(
    source: str,
    format: str = Query("csv", description="Export format: csv or excel"),
    # Student-specific filters
    account_id: str = Query(None, description="Filter by account ID"),
    course_code: str = Query(None, description="Filter by course code"),
    batch: str = Query(None, description="Filter by batch"),
    term: str = Query(None, description="Filter by term code"),
    min_marks: int = Query(None, description="Minimum marks"),
    limit: int = Query(100, description="Max records to export"),
):
    """Export data as CSV or Excel file."""

    # Build filters for student connector
    filters = {
        "account_id": account_id,
        "course_code": course_code,
        "batch": batch,
        "term": term,
        "min_marks": min_marks,
        "limit": limit,
    }
    # Remove None values
    filters = {k: v for k, v in filters.items() if v is not None}

    data = _get_data(source, **filters)

    if not data:
        return {"error": "No data found", "source": source}

    df = pd.DataFrame(data)

    if format.lower() == "excel":
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine="openpyxl")
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={source}_export.xlsx"},
        )
    else:
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={source}_export.csv"},
        )

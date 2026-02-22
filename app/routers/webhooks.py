"""
Webhook CRUD router.
Provides endpoints for registering, listing, and testing webhooks.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from typing import List, Optional
from app.auth import get_api_key
from app.services.webhook_manager import webhook_manager

router = APIRouter(prefix="/webhooks", tags=["webhooks"], dependencies=[Depends(get_api_key)])


class WebhookCreate(BaseModel):
    url: str
    events: List[str] = ["data.queried"]
    source: Optional[str] = None
    secret: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://example.com/webhook",
                "events": ["data.queried"],
                "source": "crm",
                "secret": "my-webhook-secret"
            }
        }


@router.post("/")
def register_webhook(body: WebhookCreate):
    """Register a new webhook to receive event notifications."""
    webhook = webhook_manager.register(
        url=body.url,
        events=body.events,
        source=body.source,
        secret=body.secret,
    )
    return {"message": "Webhook registered", "webhook": webhook}


@router.get("/")
def list_webhooks():
    """List all registered webhooks."""
    return {"webhooks": webhook_manager.list_all()}


@router.get("/deliveries")
def get_deliveries(webhook_id: Optional[str] = None):
    """Get webhook delivery log."""
    return {"deliveries": webhook_manager.get_delivery_log(webhook_id)}


@router.get("/{webhook_id}")
def get_webhook(webhook_id: str):
    """Get details of a specific webhook."""
    webhook = webhook_manager.get(webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return {"webhook": webhook}


@router.delete("/{webhook_id}")
def delete_webhook(webhook_id: str):
    """Unregister a webhook."""
    removed = webhook_manager.unregister(webhook_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return {"message": f"Webhook {webhook_id} removed"}


@router.post("/test/{webhook_id}")
def test_webhook(webhook_id: str):
    """Send a test payload to a webhook."""
    result = webhook_manager.send_test(webhook_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result

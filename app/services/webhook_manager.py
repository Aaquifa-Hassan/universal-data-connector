"""
Webhook manager service.
Handles webhook registration, storage, and background dispatch.
"""

import uuid
import time
import logging
import threading
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class WebhookManager:
    """In-memory webhook registry with background dispatch."""

    def __init__(self):
        self._webhooks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._delivery_log: List[Dict[str, Any]] = []

    def register(self, url: str, events: List[str], source: Optional[str] = None, secret: Optional[str] = None) -> Dict[str, Any]:
        """Register a new webhook."""
        webhook_id = str(uuid.uuid4())[:8]
        webhook = {
            "id": webhook_id,
            "url": url,
            "events": events,
            "source": source,
            "secret": secret,
            "active": True,
            "created_at": datetime.utcnow().isoformat(),
            "last_triggered": None,
            "trigger_count": 0,
        }
        with self._lock:
            self._webhooks[webhook_id] = webhook
        logger.info(f"Webhook registered: {webhook_id} -> {url} for events {events}")
        return webhook

    def unregister(self, webhook_id: str) -> bool:
        """Remove a webhook by ID."""
        with self._lock:
            if webhook_id in self._webhooks:
                del self._webhooks[webhook_id]
                logger.info(f"Webhook unregistered: {webhook_id}")
                return True
            return False

    def get(self, webhook_id: str) -> Optional[Dict[str, Any]]:
        """Get webhook details by ID."""
        with self._lock:
            return self._webhooks.get(webhook_id)

    def list_all(self) -> List[Dict[str, Any]]:
        """List all registered webhooks."""
        with self._lock:
            return list(self._webhooks.values())

    def dispatch(self, event_type: str, source: str, payload: Dict[str, Any]) -> int:
        """
        Dispatch webhook notifications to matching subscribers.
        Runs HTTP POSTs in background threads.
        Returns number of webhooks matched.
        """
        with self._lock:
            matching = [
                wh for wh in self._webhooks.values()
                if wh["active"]
                and event_type in wh["events"]
                and (wh["source"] is None or wh["source"] == source)
            ]

        if not matching:
            return 0

        envelope = {
            "event": event_type,
            "source": source,
            "timestamp": datetime.utcnow().isoformat(),
            "payload": payload,
        }

        for wh in matching:
            threading.Thread(
                target=self._deliver,
                args=(wh, envelope),
                daemon=True,
            ).start()

        return len(matching)

    def _deliver(self, webhook: Dict[str, Any], envelope: Dict[str, Any]):
        """Deliver a webhook payload via HTTP POST."""
        import json

        webhook_id = webhook["id"]
        url = webhook["url"]
        headers = {"Content-Type": "application/json"}

        if webhook.get("secret"):
            import hashlib
            import hmac
            body = json.dumps(envelope)
            sig = hmac.new(webhook["secret"].encode(), body.encode(), hashlib.sha256).hexdigest()
            headers["X-Webhook-Signature"] = sig

        delivery_entry = {
            "webhook_id": webhook_id,
            "url": url,
            "event": envelope["event"],
            "timestamp": envelope["timestamp"],
            "status": "pending",
            "response_code": None,
        }

        try:
            import httpx
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=envelope, headers=headers)
                delivery_entry["status"] = "delivered"
                delivery_entry["response_code"] = resp.status_code
                logger.info(f"Webhook {webhook_id} delivered to {url}: {resp.status_code}")
        except Exception as e:
            delivery_entry["status"] = "failed"
            delivery_entry["error"] = str(e)
            logger.warning(f"Webhook {webhook_id} delivery failed to {url}: {e}")

        # Update webhook stats
        with self._lock:
            if webhook_id in self._webhooks:
                self._webhooks[webhook_id]["last_triggered"] = envelope["timestamp"]
                self._webhooks[webhook_id]["trigger_count"] += 1
            self._delivery_log.append(delivery_entry)
            # Keep only last 100 deliveries
            if len(self._delivery_log) > 100:
                self._delivery_log = self._delivery_log[-100:]

    def get_delivery_log(self, webhook_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get delivery log, optionally filtered by webhook ID."""
        with self._lock:
            if webhook_id:
                return [d for d in self._delivery_log if d["webhook_id"] == webhook_id]
            return list(self._delivery_log)

    def send_test(self, webhook_id: str) -> Dict[str, Any]:
        """Send a test payload to a webhook."""
        webhook = self.get(webhook_id)
        if not webhook:
            return {"error": "Webhook not found"}

        test_envelope = {
            "event": "test",
            "source": "system",
            "timestamp": datetime.utcnow().isoformat(),
            "payload": {"message": "This is a test webhook delivery", "webhook_id": webhook_id},
        }

        threading.Thread(
            target=self._deliver,
            args=(webhook, test_envelope),
            daemon=True,
        ).start()

        return {"message": f"Test payload dispatched to {webhook['url']}"}


# Global webhook manager instance
webhook_manager = WebhookManager()

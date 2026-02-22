"""
Tests for bonus features: Rate Limiting, Caching, Streaming (SSE), and Webhooks.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.services.cache import data_cache

client = TestClient(app)
AUTH = {"X-API-Key": settings.API_KEY}


# ───────────────────────────────
# Rate Limiting Tests
# ───────────────────────────────

class TestRateLimiting:
    def test_normal_request_succeeds(self):
        """Single request should succeed."""
        resp = client.get("/data/crm", headers=AUTH)
        assert resp.status_code == 200

    def test_rate_limit_headers_present(self):
        """Rate limit response should include limit headers."""
        resp = client.get("/data/crm", headers=AUTH)
        # slowapi adds X-RateLimit headers
        assert resp.status_code == 200


# ───────────────────────────────
# Caching Tests
# ───────────────────────────────

class TestCaching:
    def setup_method(self):
        data_cache.clear()

    def test_cache_miss_then_hit(self):
        """First request should be a MISS, second should be a HIT."""
        resp1 = client.get("/data/crm", headers=AUTH)
        assert resp1.status_code == 200
        assert resp1.headers.get("X-Cache") == "MISS"

        resp2 = client.get("/data/crm", headers=AUTH)
        assert resp2.status_code == 200
        assert resp2.headers.get("X-Cache") == "HIT"

    def test_cache_key_returned(self):
        """Response should include X-Cache-Key header."""
        resp = client.get("/data/crm", headers=AUTH)
        assert resp.headers.get("X-Cache-Key") is not None

    def test_cache_stats(self):
        """Cache stats endpoint should return hit/miss counters."""
        data_cache.clear()
        client.get("/data/crm", headers=AUTH)
        client.get("/data/crm", headers=AUTH)

        resp = client.get("/cache/stats", headers=AUTH)
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["hits"] >= 1
        assert stats["misses"] >= 1

    def test_cache_flush(self):
        """Flushing cache should reset all entries."""
        client.get("/data/crm", headers=AUTH)
        resp = client.delete("/cache/", headers=AUTH)
        assert resp.status_code == 200
        assert "flushed" in resp.json()["message"].lower()

    def test_cache_keys(self):
        """Cache keys endpoint should list active keys."""
        data_cache.clear()
        client.get("/data/crm", headers=AUTH)
        resp = client.get("/cache/keys", headers=AUTH)
        assert resp.status_code == 200
        assert len(resp.json()["keys"]) >= 1


# ───────────────────────────────
# Streaming (SSE) Tests
# ───────────────────────────────

class TestStreaming:
    def test_stream_crm(self):
        """Streaming CRM data should return SSE events."""
        resp = client.get("/stream/crm?limit=3&delay=0", headers=AUTH)
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")

        body = resp.text
        assert "event: start" in body
        assert "event: record" in body
        assert "event: done" in body

    def test_stream_support(self):
        """Streaming support data should work."""
        resp = client.get("/stream/support?limit=2&delay=0", headers=AUTH)
        assert resp.status_code == 200
        assert "event: record" in resp.text

    def test_stream_invalid_source(self):
        """Streaming an invalid source should return an error event."""
        resp = client.get("/stream/invalid?limit=1&delay=0", headers=AUTH)
        assert resp.status_code == 200
        assert "event: error" in resp.text

    def test_stream_analytics(self):
        """Streaming analytics data should work."""
        resp = client.get("/stream/analytics?limit=3&delay=0", headers=AUTH)
        assert resp.status_code == 200
        body = resp.text
        assert "event: start" in body
        assert "event: done" in body


# ───────────────────────────────
# Webhook Tests
# ───────────────────────────────

class TestWebhooks:
    def test_register_webhook(self):
        """Should register a new webhook."""
        resp = client.post("/webhooks/", json={
            "url": "https://httpbin.org/post",
            "events": ["data.queried"],
            "source": "crm",
        }, headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert "webhook" in data
        assert data["webhook"]["url"] == "https://httpbin.org/post"

    def test_list_webhooks(self):
        """Should list registered webhooks."""
        resp = client.get("/webhooks/", headers=AUTH)
        assert resp.status_code == 200
        assert "webhooks" in resp.json()

    def test_get_webhook(self):
        """Should get a specific webhook by ID."""
        # Register first
        reg = client.post("/webhooks/", json={
            "url": "https://example.com/hook",
            "events": ["data.queried"],
        }, headers=AUTH)
        wh_id = reg.json()["webhook"]["id"]

        resp = client.get(f"/webhooks/{wh_id}", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["webhook"]["id"] == wh_id

    def test_delete_webhook(self):
        """Should delete a webhook."""
        reg = client.post("/webhooks/", json={
            "url": "https://example.com/delete-me",
            "events": ["test"],
        }, headers=AUTH)
        wh_id = reg.json()["webhook"]["id"]

        resp = client.delete(f"/webhooks/{wh_id}", headers=AUTH)
        assert resp.status_code == 200
        assert "removed" in resp.json()["message"]

    def test_delete_nonexistent_webhook(self):
        """Deleting a non-existent webhook should return 404."""
        resp = client.delete("/webhooks/nonexistent", headers=AUTH)
        assert resp.status_code == 404

    def test_get_nonexistent_webhook(self):
        """Getting a non-existent webhook should return 404."""
        resp = client.get("/webhooks/nonexistent", headers=AUTH)
        assert resp.status_code == 404

    def test_delivery_log(self):
        """Should return delivery log."""
        resp = client.get("/webhooks/deliveries", headers=AUTH)
        assert resp.status_code == 200
        assert "deliveries" in resp.json()

    def test_test_webhook(self):
        """Should send a test payload to a webhook."""
        reg = client.post("/webhooks/", json={
            "url": "https://httpbin.org/post",
            "events": ["test"],
        }, headers=AUTH)
        wh_id = reg.json()["webhook"]["id"]

        resp = client.post(f"/webhooks/test/{wh_id}", headers=AUTH)
        assert resp.status_code == 200
        assert "dispatched" in resp.json()["message"]


# ───────────────────────────────
# Auth on new endpoints
# ───────────────────────────────

class TestBonusAuth:
    def test_cache_requires_auth(self):
        resp = client.get("/cache/stats")
        assert resp.status_code == 401

    def test_stream_requires_auth(self):
        resp = client.get("/stream/crm")
        assert resp.status_code == 401

    def test_webhooks_requires_auth(self):
        resp = client.get("/webhooks/")
        assert resp.status_code == 401

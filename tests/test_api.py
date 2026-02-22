from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

client = TestClient(app)
auth_headers = {"X-API-Key": settings.API_KEY}

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_get_crm_data():
    response = client.get("/data/crm", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "metadata" in data
    assert len(data["data"]) <= 3  # Voice limits applied

def test_get_support_data():
    response = client.get("/data/support", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "metadata" in data

def test_get_analytics_data():
    response = client.get("/data/analytics", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "metadata" in data

def test_get_invalid_source():
    response = client.get("/data/invalid", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["data"] == []
    assert data["metadata"]["total_results"] == 0

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")

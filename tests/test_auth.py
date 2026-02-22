from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_auth_missing_header():
    """Test accessing protected endpoint without API Key"""
    response = client.get("/data/crm")
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API Key"}

def test_auth_invalid_key():
    """Test accessing protected endpoint with invalid API Key"""
    response = client.get("/data/crm", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API Key"}

def test_auth_valid_key():
    """Test accessing protected endpoint with valid API Key"""
    response = client.get("/data/crm", headers={"X-API-Key": "secret-api-key"})
    assert response.status_code == 200

def test_public_endpoint_access():
    """Test public endpoints (health, root) remain accessible without auth"""
    response = client.get("/health")
    assert response.status_code == 200
    
    response = client.get("/")
    assert response.status_code == 200

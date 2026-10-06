"""Integration tests for health endpoints."""

import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import settings


@pytest.fixture
def client():
    """Create a test client fixture for the FastAPI app."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_root_endpoint(client):
    """Test the root informative endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert data["version"] == settings.APP_VERSION
    assert data["health"] == "/api/v1/health"


def test_health_check_healthy(client):
    """Test health check returns 200 and healthy status under normal conditions."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app_name"] == settings.APP_NAME
    assert data["storage_accessible"] is True
    assert "details" in data
    assert "default_llm" in data["details"]


def test_health_check_storage_failure(monkeypatch, client):
    """Test health check returns degraded status if storage path is inaccessible."""
    # Mock settings.STORAGE_PATH to an impossible/invalid path or mock touch to raise
    from pathlib import Path
    class BrokenPath(Path):
        def mkdir(self, *args, **kwargs):
            raise PermissionError("Access denied to storage volume")

    monkeypatch.setattr(settings, "STORAGE_PATH", BrokenPath("Z:/invalid_drive/non_existent"))

    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["storage_accessible"] is False

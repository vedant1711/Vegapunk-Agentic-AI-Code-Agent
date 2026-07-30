"""Tests for the FastAPI API endpoints."""

from fastapi.testclient import TestClient


def test_root_endpoint():
    """Test the root health check endpoint."""
    # Import here to avoid config issues during collection
    from app.main import app

    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Vegapunk"
    assert data["version"] == "0.1.0"
    assert "providers" in data


def test_health_endpoint():
    """Test the health check endpoint."""
    from app.main import app

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] == "healthy"


def test_create_task():
    """Test creating a task via the API."""
    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/api/tasks/",
        json={
            "repo_full_name": "test-owner/test-repo",
            "issue_number": 1,
            "issue_title": "Test issue",
            "issue_body": "This is a test issue body.",
            "issue_labels": ["bug"],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data
    assert data["status"] == "queued"


def test_list_tasks():
    """Test listing tasks."""
    from app.main import app

    client = TestClient(app)
    response = client.get("/api/tasks/")

    assert response.status_code == 200
    data = response.json()
    assert "tasks" in data


def test_get_nonexistent_task():
    """Test getting a task that doesn't exist."""
    from app.main import app

    client = TestClient(app)
    response = client.get("/api/tasks/nonexistent")

    assert response.status_code == 200
    data = response.json()
    assert "error" in data


def test_webhook_with_invalid_payload():
    """Test webhook with non-matching event."""
    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/api/webhooks/github",
        json={"action": "closed"},
        headers={"X-GitHub-Event": "ping"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ignored"

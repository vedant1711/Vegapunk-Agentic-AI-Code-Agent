"""Tests for the /api/tasks/demo endpoint.

Confirms the pre-recorded transcript loads, an SSE stream emits the
expected structural events, and the run terminates cleanly. Uses a
short synthetic transcript so the test finishes in under a second.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def short_transcript(monkeypatch, tmp_path):
    """Swap in a tiny 4-entry transcript so the test isn't slow."""
    transcript = [
        {"delay_ms": 0,  "type": "log",        "step": "System", "message": "Task started (demo)"},
        {"delay_ms": 10, "type": "step_start", "step": "Setup"},
        {"delay_ms": 10, "type": "step_end",   "step": "Setup",  "status": "success", "duration_ms": 20},
        {
            "delay_ms": 10, "type": "run_end", "step": "System",
            "message": "Run finished.", "level": "success", "duration_ms": 30,
        },
    ]
    fake_path = tmp_path / "transcript.json"
    fake_path.write_text(json.dumps(transcript))
    # Patch the module-level constant that _run_demo reads
    monkeypatch.setattr("app.api.tasks._DEMO_TRANSCRIPT_PATH", fake_path)
    return transcript


def test_demo_endpoint_returns_task_id(short_transcript):
    from app.main import app
    client = TestClient(app)
    response = client.post("/api/tasks/demo")
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"].startswith("demo-")
    assert data["status"] == "queued"
    assert data["demo"] is True


def test_demo_endpoint_emits_sse_events(short_transcript):
    from app.main import app
    client = TestClient(app)
    task_id = client.post("/api/tasks/demo").json()["task_id"]

    with client.stream("GET", f"/api/tasks/{task_id}/events") as resp:
        assert resp.status_code == 200
        events = []
        for line in resp.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
                if events[-1].get("event_type") == "run_end":
                    break

    assert any(e.get("event_type") == "step_start" for e in events)
    assert any(e.get("event_type") == "step_end" for e in events)
    assert any(e.get("event_type") == "run_end" for e in events)


def test_demo_endpoint_handles_missing_transcript(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.api.tasks._DEMO_TRANSCRIPT_PATH",
        tmp_path / "does_not_exist.json",
    )
    from app.main import app
    client = TestClient(app)
    task_id = client.post("/api/tasks/demo").json()["task_id"]

    with client.stream("GET", f"/api/tasks/{task_id}/events") as resp:
        seen_error = False
        for line in resp.iter_lines():
            if line.startswith("data:"):
                event = json.loads(line[5:].strip())
                if event.get("event_type") == "run_end" and event.get("level") == "error":
                    seen_error = True
                    break
        assert seen_error, "expected a run_end event with level=error when transcript is missing"

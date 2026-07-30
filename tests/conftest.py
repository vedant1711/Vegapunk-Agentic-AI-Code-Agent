"""Shared pytest fixtures.

An autouse fixture here scrubs credential-bearing settings before every
test so unit tests can't accidentally pass or fail based on whether the
developer's local .env happens to define secrets.

Historically this bit us: `test_webhook_with_invalid_payload` flipped to
401 whenever `GITHUB_WEBHOOK_SECRET` was set in the environment. Fixture
below prevents that class of leakage across the whole suite.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    """Clear ambient credentials from the singleton settings object.

    The pydantic BaseSettings singleton `app.config.settings` is imported
    at module load, so environment changes made mid-test don't propagate.
    Instead we monkeypatch attributes on the live object, which pytest
    auto-reverts after the test.
    """
    from app.config import settings

    for attr in (
        "github_webhook_secret",
        "github_token",
        "nvidia_api_key",
        "gemini_api_key",
    ):
        if hasattr(settings, attr):
            monkeypatch.setattr(settings, attr, "")

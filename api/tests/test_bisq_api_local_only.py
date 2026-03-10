"""Tests for BISQ_API_LOCAL_ONLY safety guard."""

import pytest

from app.core.config import Settings


def test_bisq_api_local_only_allows_local_harness_host(monkeypatch):
    monkeypatch.setenv("BISQ_API_LOCAL_ONLY", "true")
    monkeypatch.setenv("BISQ_API_URL", "http://host.docker.internal:8090")

    settings = Settings(_env_file=None)

    assert settings.BISQ_API_LOCAL_ONLY is True
    assert settings.BISQ_API_URL == "http://host.docker.internal:8090"


def test_bisq_api_local_only_allows_loopback_hosts(monkeypatch):
    monkeypatch.setenv("BISQ_API_LOCAL_ONLY", "true")
    monkeypatch.setenv("BISQ_API_URL", "http://localhost:8090")
    settings = Settings(_env_file=None)
    assert settings.BISQ_API_URL == "http://localhost:8090"

    monkeypatch.setenv("BISQ_API_URL", "http://127.0.0.1:8090")
    settings = Settings(_env_file=None)
    assert settings.BISQ_API_URL == "http://127.0.0.1:8090"


def test_bisq_api_local_only_rejects_non_local_hosts(monkeypatch):
    monkeypatch.setenv("BISQ_API_LOCAL_ONLY", "true")
    monkeypatch.setenv("BISQ_API_URL", "https://api.bisq.markets:443")

    with pytest.raises(ValueError, match="BISQ_API_URL must target a local host"):
        Settings(_env_file=None)

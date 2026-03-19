"""Tests for channel enablement flags in runtime settings."""

from app.core.config import Settings


def test_bisq2_channel_enabled_reads_from_env(monkeypatch):
    monkeypatch.setenv("BISQ2_CHANNEL_ENABLED", "true")
    settings = Settings(_env_file=None)
    assert settings.BISQ2_CHANNEL_ENABLED is True


def test_channel_enabled_defaults_are_stable(monkeypatch):
    monkeypatch.delenv("BISQ2_CHANNEL_ENABLED", raising=False)
    monkeypatch.delenv("WEB_CHANNEL_ENABLED", raising=False)
    settings = Settings(_env_file=None)
    assert settings.BISQ2_CHANNEL_ENABLED is False
    assert settings.WEB_CHANNEL_ENABLED is True


def test_bisq2_chatops_settings_are_parsed(monkeypatch):
    monkeypatch.setenv("BISQ2_CHATOPS_ENABLED", "true")
    monkeypatch.setenv("BISQ2_CHATOPS_CHANNEL_IDS", "support.staff, support.ops")

    settings = Settings(_env_file=None)

    assert settings.BISQ2_CHATOPS_ENABLED is True
    assert settings.BISQ2_CHATOPS_CHANNEL_IDS == ["support.staff", "support.ops"]

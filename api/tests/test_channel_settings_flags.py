"""Tests for channel enablement flags in runtime settings."""

import logging

import pytest
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


def test_bisq2_test_allowlists_default_to_deny_all(monkeypatch):
    monkeypatch.delenv("BISQ2_ALLOWED_CHANNEL_IDS", raising=False)
    monkeypatch.delenv("BISQ2_ALLOWED_SENDER_PROFILE_IDS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.BISQ2_ALLOWED_CHANNEL_IDS == ""
    assert settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS == ""


def test_bisq2_test_allowlists_read_csv_from_env(monkeypatch):
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope

    monkeypatch.setenv(
        "BISQ2_ALLOWED_CHANNEL_IDS",
        "support.alpha, support.beta",
    )
    monkeypatch.setenv(
        "BISQ2_ALLOWED_SENDER_PROFILE_IDS",
        "profile.alpha, profile.beta",
    )
    settings = Settings(_env_file=None)

    scope = resolve_bisq2_test_scope(settings)
    assert scope.ready is True
    assert scope.channel_count == 2
    assert scope.sender_profile_count == 2


@pytest.mark.parametrize(
    ("field_name", "malformed_value", "expected_reason"),
    [
        (
            "BISQ2_STAFF_PROFILE_IDS",
            ["private-profile", 7],
            "invalid_staff_profile_scope",
        ),
        (
            "BISQ2_CHATOPS_CHANNEL_IDS",
            ["private-channel", 7],
            "invalid_chatops_scope",
        ),
        (
            "BISQ2_STAFF_PROFILE_IDS",
            "private-profile,,second-profile",
            "invalid_staff_profile_scope",
        ),
        (
            "BISQ2_ALLOWED_CHANNEL_IDS",
            ["private-channel", 7],
            "invalid_channel_allowlist",
        ),
        (
            "BISQ2_ALLOWED_SENDER_PROFILE_IDS",
            "private-profile,,second-profile",
            "invalid_sender_allowlist",
        ),
    ],
)
def test_malformed_bisq_secondary_scope_denies_without_echoing_input(
    field_name,
    malformed_value,
    expected_reason,
    caplog,
):
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope
    from app.channels.runtime import ChannelRuntime

    private_values = ("private-profile", "private-channel", "second-profile")
    setting_values = {
        "BISQ2_ALLOWED_CHANNEL_IDS": "private-channel",
        "BISQ2_ALLOWED_SENDER_PROFILE_IDS": "private-profile,second-profile",
        field_name: malformed_value,
    }
    settings = Settings(_env_file=None, **setting_values)
    scope = resolve_bisq2_test_scope(settings)
    runtime = ChannelRuntime(settings=settings)

    with caplog.at_level(logging.WARNING):
        Bisq2Channel(runtime)

    output = repr(scope) + caplog.text
    assert scope.ready is False
    assert scope.reason == expected_reason
    for private_value in private_values:
        assert private_value not in output

"""Tests for channel-level autoresponse policy persistence."""

from __future__ import annotations

import pytest
from app.services.channel_autoresponse_policy_service import (
    DEFAULT_AUTORESPONSE_ENABLED,
    DEFAULT_GENERATION_ENABLED,
    SUPPORTED_CHANNELS,
    ChannelAutoResponsePolicyService,
)


def test_service_seeds_default_policies(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))

    policies = service.list_policies()
    assert [policy.channel_id for policy in policies] == sorted(SUPPORTED_CHANNELS)

    for policy in policies:
        assert policy.enabled == DEFAULT_AUTORESPONSE_ENABLED[policy.channel_id]
        assert (
            policy.generation_enabled == DEFAULT_GENERATION_ENABLED[policy.channel_id]
        )
        assert policy.updated_at

    assert DEFAULT_AUTORESPONSE_ENABLED == {
        "web": True,
        "matrix": False,
        "bisq2": False,
    }
    assert DEFAULT_GENERATION_ENABLED == {
        "web": True,
        "matrix": False,
        "bisq2": False,
    }


def test_set_enabled_persists_value(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))

    updated = service.set_enabled("web", False)
    fetched = service.get_policy("web")

    assert updated.channel_id == "web"
    assert updated.enabled is False
    assert fetched.enabled is False
    assert fetched.generation_enabled is True


def test_set_generation_enabled_turns_on_generation_without_autosend(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))

    updated = service.set_generation_enabled("matrix", True)
    fetched = service.get_policy("matrix")

    assert updated.channel_id == "matrix"
    assert updated.generation_enabled is True
    assert fetched.generation_enabled is True
    assert fetched.enabled is False


def test_disabling_generation_forces_autosend_off(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))

    service.set_policy("web", enabled=True, generation_enabled=True)
    updated = service.set_policy("web", generation_enabled=False)

    assert updated.generation_enabled is False
    assert updated.enabled is False


def test_invalid_channel_raises_value_error(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))

    with pytest.raises(ValueError):
        service.get_policy("unknown")

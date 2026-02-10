"""Tests for escalation feature flags and rollout gates."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.hooks.escalation_hook import EscalationPostHook
from app.channels.models import (
    ChannelType,
    IncomingMessage,
    OutgoingMessage,
    ResponseMetadata,
    UserContext,
)


def _make_incoming():
    return IncomingMessage(
        message_id="msg-flag-001",
        channel=ChannelType.WEB,
        question="Test question?",
        user=UserContext(
            user_id="u1",
            session_id=None,
            channel_user_id=None,
            auth_token=None,
        ),
    )


def _make_outgoing(requires_human=True):
    return OutgoingMessage(
        message_id="out-flag-001",
        in_reply_to="msg-flag-001",
        channel=ChannelType.WEB,
        answer="AI draft answer",
        user=UserContext(
            user_id="u1",
            session_id=None,
            channel_user_id=None,
            auth_token=None,
        ),
        metadata=ResponseMetadata(
            processing_time_ms=100.0,
            rag_strategy="hybrid",
            model_name="gpt-4",
            confidence_score=0.3,
            version_confidence=None,
        ),
        requires_human=requires_human,
    )


class TestEscalationEnabledFlag:
    """Test ESCALATION_ENABLED feature flag behavior."""

    @pytest.mark.asyncio
    async def test_hook_skips_when_disabled(self):
        """Hook returns None without creating escalation when disabled."""
        settings = MagicMock()
        settings.ESCALATION_ENABLED = False

        service = AsyncMock()
        registry = MagicMock()

        hook = EscalationPostHook(service, registry, settings=settings)
        result = await hook.execute(_make_incoming(), _make_outgoing())

        assert result is None
        service.create_escalation.assert_not_called()

    @pytest.mark.asyncio
    async def test_hook_works_when_enabled(self):
        """Hook creates escalation when enabled."""
        settings = MagicMock()
        settings.ESCALATION_ENABLED = True

        service = AsyncMock()
        service.create_escalation = AsyncMock(return_value=MagicMock(id=1))
        registry = MagicMock()
        adapter = MagicMock()
        adapter.format_escalation_message = MagicMock(return_value="Escalated")
        registry.get = MagicMock(return_value=adapter)

        hook = EscalationPostHook(service, registry, settings=settings)
        await hook.execute(_make_incoming(), _make_outgoing())

        service.create_escalation.assert_called_once()

    @pytest.mark.asyncio
    async def test_hook_defaults_to_enabled_when_no_settings(self):
        """Without settings, hook defaults to enabled."""
        service = AsyncMock()
        service.create_escalation = AsyncMock(return_value=MagicMock(id=1))
        registry = MagicMock()
        adapter = MagicMock()
        adapter.format_escalation_message = MagicMock(return_value="Escalated")
        registry.get = MagicMock(return_value=adapter)

        hook = EscalationPostHook(service, registry, settings=None)
        await hook.execute(_make_incoming(), _make_outgoing())

        service.create_escalation.assert_called_once()

    @pytest.mark.asyncio
    async def test_hook_still_passes_through_non_human(self):
        """Even when enabled, non-human messages pass through."""
        settings = MagicMock()
        settings.ESCALATION_ENABLED = True

        service = AsyncMock()
        registry = MagicMock()

        hook = EscalationPostHook(service, registry, settings=settings)
        result = await hook.execute(
            _make_incoming(), _make_outgoing(requires_human=False)
        )

        assert result is None
        service.create_escalation.assert_not_called()


class TestConfigSettings:
    """Test that config has the expected escalation settings."""

    def test_config_has_escalation_enabled(self):
        """Settings class has ESCALATION_ENABLED field."""
        from app.core.config import Settings

        assert "ESCALATION_ENABLED" in Settings.model_fields

    def test_config_has_bisq2_ws_enabled(self):
        """Settings class has ESCALATION_BISQ2_WS_ENABLED field."""
        from app.core.config import Settings

        assert "ESCALATION_BISQ2_WS_ENABLED" in Settings.model_fields

    def test_config_has_poll_timeout(self):
        """Settings class has ESCALATION_POLL_TIMEOUT_MINUTES field."""
        from app.core.config import Settings

        assert "ESCALATION_POLL_TIMEOUT_MINUTES" in Settings.model_fields

    def test_escalation_enabled_defaults_true(self):
        """ESCALATION_ENABLED defaults to True."""
        from app.core.config import Settings

        field_info = Settings.model_fields["ESCALATION_ENABLED"]
        assert field_info.default is True

    def test_bisq2_ws_defaults_false(self):
        """ESCALATION_BISQ2_WS_ENABLED defaults to False."""
        from app.core.config import Settings

        field_info = Settings.model_fields["ESCALATION_BISQ2_WS_ENABLED"]
        assert field_info.default is False

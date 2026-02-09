"""Tests for Channel Configuration models.

TDD tests for channel-specific configuration validation.
"""

import pytest
from pydantic import ValidationError


class TestChannelConfigBase:
    """Test base channel configuration."""

    @pytest.mark.unit
    def test_default_config_values(self):
        """Default config has sensible values."""
        from app.channels.config import ChannelConfigBase

        config = ChannelConfigBase()
        assert config.enabled is True
        assert config.rate_limit_per_minute > 0
        assert config.max_message_bytes > 0

    @pytest.mark.unit
    def test_rate_limit_bounds(self):
        """Rate limit must be within bounds."""
        from app.channels.config import ChannelConfigBase

        # Valid bounds
        config = ChannelConfigBase(rate_limit_per_minute=1)
        assert config.rate_limit_per_minute == 1

        config = ChannelConfigBase(rate_limit_per_minute=1000)
        assert config.rate_limit_per_minute == 1000

        # Invalid bounds
        with pytest.raises(ValidationError):
            ChannelConfigBase(rate_limit_per_minute=0)

        with pytest.raises(ValidationError):
            ChannelConfigBase(rate_limit_per_minute=1001)


class TestBisq2ChannelConfig:
    """Test Bisq2 channel configuration."""

    @pytest.mark.unit
    def test_default_bisq2_config(self):
        """Default Bisq2 config has correct values."""
        from app.channels.config import Bisq2ChannelConfig

        config = Bisq2ChannelConfig()
        assert config.enabled is True
        assert "bisq2-api" in config.api_url
        assert config.poll_interval_seconds > 0

    @pytest.mark.unit
    def test_poll_interval_bounds(self):
        """Poll interval must be within bounds."""
        from app.channels.config import Bisq2ChannelConfig

        # Valid
        config = Bisq2ChannelConfig(poll_interval_seconds=10)
        assert config.poll_interval_seconds == 10

        # Invalid (too low)
        with pytest.raises(ValidationError):
            Bisq2ChannelConfig(poll_interval_seconds=5)

        # Invalid (too high)
        with pytest.raises(ValidationError):
            Bisq2ChannelConfig(poll_interval_seconds=3601)

    @pytest.mark.unit
    def test_export_batch_size_bounds(self):
        """Export batch size must be within bounds."""
        from app.channels.config import Bisq2ChannelConfig

        config = Bisq2ChannelConfig(export_batch_size=10)
        assert config.export_batch_size == 10

        config = Bisq2ChannelConfig(export_batch_size=500)
        assert config.export_batch_size == 500

        config = Bisq2ChannelConfig(export_batch_size=1000)
        assert config.export_batch_size == 1000

        with pytest.raises(ValidationError):
            Bisq2ChannelConfig(export_batch_size=9)

        with pytest.raises(ValidationError):
            Bisq2ChannelConfig(export_batch_size=1001)


class TestWebChannelConfig:
    """Test Web channel configuration."""

    @pytest.mark.unit
    def test_default_web_config(self):
        """Default Web config has correct values."""
        from app.channels.config import WebChannelConfig

        config = WebChannelConfig()
        assert config.enabled is True
        assert isinstance(config.cors_origins, list)
        assert config.max_chat_history >= 0

    @pytest.mark.unit
    def test_max_chat_history_bounds(self):
        """Max chat history must be within bounds."""
        from app.channels.config import WebChannelConfig

        config = WebChannelConfig(max_chat_history=0)
        assert config.max_chat_history == 0

        config = WebChannelConfig(max_chat_history=50)
        assert config.max_chat_history == 50

        with pytest.raises(ValidationError):
            WebChannelConfig(max_chat_history=-1)

        with pytest.raises(ValidationError):
            WebChannelConfig(max_chat_history=51)


class TestMatrixChannelConfig:
    """Test Matrix channel configuration."""

    @pytest.mark.unit
    def test_default_matrix_config_disabled(self):
        """Default Matrix config is disabled."""
        from app.channels.config import MatrixChannelConfig

        config = MatrixChannelConfig(enabled=False)
        assert config.enabled is False

    @pytest.mark.unit
    def test_enabled_matrix_requires_homeserver_url(self):
        """Enabled Matrix requires homeserver_url."""
        from app.channels.config import MatrixChannelConfig

        with pytest.raises(ValidationError, match="homeserver_url"):
            MatrixChannelConfig(
                enabled=True,
                homeserver_url="",
                user_id="@bot:matrix.org",
                rooms=["!room:matrix.org"],
            )

    @pytest.mark.unit
    def test_enabled_matrix_requires_user_id(self):
        """Enabled Matrix requires user_id."""
        from app.channels.config import MatrixChannelConfig

        with pytest.raises(ValidationError, match="user_id"):
            MatrixChannelConfig(
                enabled=True,
                homeserver_url="https://matrix.org",
                user_id="",
                rooms=["!room:matrix.org"],
            )

    @pytest.mark.unit
    def test_enabled_matrix_requires_rooms(self):
        """Enabled Matrix requires at least one room."""
        from app.channels.config import MatrixChannelConfig

        with pytest.raises(ValidationError, match="rooms"):
            MatrixChannelConfig(
                enabled=True,
                homeserver_url="https://matrix.org",
                user_id="@bot:matrix.org",
                rooms=[],
            )

    @pytest.mark.unit
    def test_room_id_format_validation(self):
        """Room IDs must start with !."""
        from app.channels.config import MatrixChannelConfig

        with pytest.raises(ValidationError, match="Invalid room ID"):
            MatrixChannelConfig(
                enabled=True,
                homeserver_url="https://matrix.org",
                user_id="@bot:matrix.org",
                rooms=["invalid_room"],  # Doesn't start with !
            )

    @pytest.mark.unit
    def test_valid_matrix_config(self):
        """Valid Matrix config passes validation."""
        from app.channels.config import MatrixChannelConfig

        config = MatrixChannelConfig(
            enabled=True,
            homeserver_url="https://matrix.org",
            user_id="@bot:matrix.org",
            rooms=["!room1:matrix.org", "!room2:matrix.org"],
        )
        assert config.enabled is True
        assert len(config.rooms) == 2


class TestChannelsConfig:
    """Test aggregate channel configuration."""

    @pytest.mark.unit
    def test_default_channels_config(self):
        """Default config has at least one enabled channel."""
        from app.channels.config import ChannelsConfig

        config = ChannelsConfig()
        # Web is enabled by default
        assert config.web.enabled is True

    @pytest.mark.unit
    def test_at_least_one_channel_required(self):
        """At least one channel must be enabled."""
        from app.channels.config import (
            Bisq2ChannelConfig,
            ChannelsConfig,
            MatrixChannelConfig,
            WebChannelConfig,
        )

        with pytest.raises(ValidationError, match=r"(?i)at least one"):
            ChannelsConfig(
                bisq2=Bisq2ChannelConfig(enabled=False),
                web=WebChannelConfig(enabled=False),
                matrix=MatrixChannelConfig(enabled=False),
            )

    @pytest.mark.unit
    def test_multiple_channels_enabled(self):
        """Multiple channels can be enabled."""
        from app.channels.config import (
            Bisq2ChannelConfig,
            ChannelsConfig,
            MatrixChannelConfig,
            WebChannelConfig,
        )

        config = ChannelsConfig(
            bisq2=Bisq2ChannelConfig(enabled=True),
            web=WebChannelConfig(enabled=True),
            matrix=MatrixChannelConfig(
                enabled=True,
                homeserver_url="https://matrix.org",
                user_id="@bot:matrix.org",
                rooms=["!room:matrix.org"],
            ),
        )
        assert config.bisq2.enabled is True
        assert config.web.enabled is True
        assert config.matrix.enabled is True

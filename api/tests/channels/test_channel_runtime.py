"""Tests for ChannelRuntime (Dependency Injection Container).

TDD tests for service registration and resolution.
"""

import logging
from unittest.mock import MagicMock

import pytest


class TestChannelRuntimeRegistration:
    """Test service registration."""

    @pytest.mark.unit
    def test_register_singleton_service(self):
        """Register singleton lifetime service."""
        from app.channels.runtime import ChannelRuntime

        runtime = ChannelRuntime(settings=MagicMock())
        service = MagicMock()

        runtime.register("test_service", service)
        resolved = runtime.resolve("test_service")

        assert resolved is service

    @pytest.mark.unit
    def test_register_with_factory(self):
        """Register using factory function."""
        from app.channels.runtime import ChannelRuntime

        runtime = ChannelRuntime(settings=MagicMock())

        def factory():
            return MagicMock(name="from_factory")

        runtime.register_factory("test_service", factory)
        resolved = runtime.resolve("test_service")

        assert resolved is not None
        assert resolved._mock_name == "from_factory"

    @pytest.mark.unit
    def test_register_instance_directly(self):
        """Register pre-created instance."""
        from app.channels.runtime import ChannelRuntime

        runtime = ChannelRuntime(settings=MagicMock())
        instance = {"key": "value"}

        runtime.register("config", instance)
        resolved = runtime.resolve("config")

        assert resolved is instance
        assert resolved["key"] == "value"

    @pytest.mark.unit
    def test_register_duplicate_raises_error(self):
        """Duplicate registration raises error."""
        from app.channels.runtime import ChannelRuntime, ServiceAlreadyRegisteredError

        runtime = ChannelRuntime(settings=MagicMock())
        runtime.register("test_service", MagicMock())

        with pytest.raises(ServiceAlreadyRegisteredError):
            runtime.register("test_service", MagicMock())

    @pytest.mark.unit
    def test_register_allows_override_with_flag(self):
        """Can override registration with explicit flag."""
        from app.channels.runtime import ChannelRuntime

        runtime = ChannelRuntime(settings=MagicMock())
        service1 = MagicMock(name="service1")
        service2 = MagicMock(name="service2")

        runtime.register("test_service", service1)
        runtime.register("test_service", service2, allow_override=True)

        resolved = runtime.resolve("test_service")
        assert resolved._mock_name == "service2"


class TestChannelRuntimeResolution:
    """Test service resolution."""

    @pytest.mark.unit
    def test_resolve_registered_service(self):
        """Resolve service by name."""
        from app.channels.runtime import ChannelRuntime

        runtime = ChannelRuntime(settings=MagicMock())
        service = MagicMock()

        runtime.register("rag_service", service)
        resolved = runtime.resolve("rag_service")

        assert resolved is service

    @pytest.mark.unit
    def test_resolve_unregistered_raises_error(self):
        """Unknown service raises ServiceNotFoundError."""
        from app.channels.runtime import ChannelRuntime, ServiceNotFoundError

        runtime = ChannelRuntime(settings=MagicMock())

        with pytest.raises(ServiceNotFoundError):
            runtime.resolve("nonexistent")

    @pytest.mark.unit
    def test_resolve_singleton_returns_same_instance(self):
        """Singleton returns same instance."""
        from app.channels.runtime import ChannelRuntime

        runtime = ChannelRuntime(settings=MagicMock())

        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return MagicMock()

        runtime.register_factory("test_service", factory, singleton=True)

        instance1 = runtime.resolve("test_service")
        instance2 = runtime.resolve("test_service")

        assert instance1 is instance2
        assert call_count == 1  # Factory called only once

    @pytest.mark.unit
    def test_resolve_transient_returns_new_instance(self):
        """Transient service returns new instance each time."""
        from app.channels.runtime import ChannelRuntime

        runtime = ChannelRuntime(settings=MagicMock())

        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return MagicMock()

        runtime.register_factory("test_service", factory, singleton=False)

        instance1 = runtime.resolve("test_service")
        instance2 = runtime.resolve("test_service")

        assert instance1 is not instance2
        assert call_count == 2

    @pytest.mark.unit
    def test_resolve_optional_returns_none_if_missing(self):
        """Optional resolution returns None for missing service."""
        from app.channels.runtime import ChannelRuntime

        runtime = ChannelRuntime(settings=MagicMock())
        result = runtime.resolve_optional("nonexistent")

        assert result is None


class TestChannelRuntimePluginServices:
    """Test plugin-specific injection."""

    @pytest.mark.unit
    def test_inject_rag_service_into_plugin(self):
        """Inject RAG service."""
        from app.channels.runtime import ChannelRuntime

        settings = MagicMock()
        rag_service = MagicMock()

        runtime = ChannelRuntime(settings=settings, rag_service=rag_service)

        assert runtime.rag_service is rag_service

    @pytest.mark.unit
    def test_inject_settings_into_plugin(self):
        """Inject Settings."""
        from app.channels.runtime import ChannelRuntime

        settings = MagicMock()
        settings.MODEL_NAME = "gpt-4"

        runtime = ChannelRuntime(settings=settings)

        assert runtime.settings is settings
        assert runtime.settings.MODEL_NAME == "gpt-4"

    @pytest.mark.unit
    def test_plugin_receives_channel_specific_config(self):
        """Plugin gets its channel config."""
        from app.channels.runtime import ChannelRuntime

        settings = MagicMock()
        settings.channels = MagicMock()
        settings.channels.matrix = MagicMock(
            enabled=True, homeserver_url="https://matrix.org"
        )

        runtime = ChannelRuntime(settings=settings)
        config = runtime.get_channel_config("matrix")

        assert config.enabled is True
        assert config.homeserver_url == "https://matrix.org"

    @pytest.mark.unit
    def test_inject_metrics_collector_into_plugin(self):
        """Inject metrics collector."""
        from app.channels.runtime import ChannelRuntime

        settings = MagicMock()
        metrics = MagicMock()

        runtime = ChannelRuntime(settings=settings, metrics=metrics)

        assert runtime.metrics is metrics

    @pytest.mark.unit
    def test_inject_feedback_service(self):
        """Inject feedback service."""
        from app.channels.runtime import ChannelRuntime

        settings = MagicMock()
        feedback_service = MagicMock()

        runtime = ChannelRuntime(settings=settings, feedback_service=feedback_service)

        assert runtime.feedback_service is feedback_service


class TestChannelRuntimeLogging:
    """Test logging functionality."""

    @pytest.mark.unit
    def test_get_logger_for_channel(self):
        """Get logger with channel-specific name."""
        from app.channels.runtime import ChannelRuntime

        runtime = ChannelRuntime(settings=MagicMock())
        logger = runtime.get_logger("matrix")

        assert isinstance(logger, logging.Logger)
        assert logger.name == "channel.matrix"

    @pytest.mark.unit
    def test_get_logger_for_different_channels(self):
        """Different channels get different loggers."""
        from app.channels.runtime import ChannelRuntime

        runtime = ChannelRuntime(settings=MagicMock())
        logger1 = runtime.get_logger("matrix")
        logger2 = runtime.get_logger("bisq2")

        assert logger1.name == "channel.matrix"
        assert logger2.name == "channel.bisq2"
        assert logger1 is not logger2


class TestChannelRuntimeConfigAccess:
    """Test configuration access."""

    @pytest.mark.unit
    def test_get_channel_config_returns_channel_config(self):
        """Get channel-specific configuration."""
        from app.channels.runtime import ChannelRuntime

        settings = MagicMock()
        settings.channels = MagicMock()
        settings.channels.web = MagicMock(enabled=True, max_chat_history=10)

        runtime = ChannelRuntime(settings=settings)
        config = runtime.get_channel_config("web")

        assert config.enabled is True
        assert config.max_chat_history == 10

    @pytest.mark.unit
    def test_get_channel_config_returns_default_for_missing(self):
        """Returns default config for unconfigured channel."""
        from app.channels.runtime import ChannelRuntime

        settings = MagicMock()
        settings.channels = MagicMock(spec=[])  # No attributes

        runtime = ChannelRuntime(settings=settings)
        config = runtime.get_channel_config("nonexistent")

        # Should return a default config, not None or raise
        assert config is not None
        assert hasattr(config, "enabled")

    @pytest.mark.unit
    def test_get_enabled_channels(self):
        """Get list of enabled channel types."""
        from app.channels.runtime import ChannelRuntime

        settings = MagicMock()
        settings.channels = MagicMock()
        settings.channels.web = MagicMock(enabled=True)
        settings.channels.matrix = MagicMock(enabled=False)
        settings.channels.bisq2 = MagicMock(enabled=True)

        runtime = ChannelRuntime(settings=settings)
        enabled = runtime.get_enabled_channels()

        assert "web" in enabled
        assert "bisq2" in enabled
        assert "matrix" not in enabled


class TestChannelRuntimeLifecycle:
    """Test runtime lifecycle."""

    @pytest.mark.unit
    def test_runtime_has_started_flag(self):
        """Runtime tracks if it has been started."""
        from app.channels.runtime import ChannelRuntime

        runtime = ChannelRuntime(settings=MagicMock())
        assert runtime.is_started is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_runtime_start_sets_flag(self):
        """Start sets the started flag."""
        from app.channels.runtime import ChannelRuntime

        runtime = ChannelRuntime(settings=MagicMock())
        await runtime.start()

        assert runtime.is_started is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_runtime_stop_clears_flag(self):
        """Stop clears the started flag."""
        from app.channels.runtime import ChannelRuntime

        runtime = ChannelRuntime(settings=MagicMock())
        await runtime.start()
        await runtime.stop()

        assert runtime.is_started is False

"""Tests for ChannelRegistry.

TDD tests for channel registration and lifecycle management.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import HealthStatus


class TestChannelRegistryRegistration:
    """Test plugin registration."""

    @pytest.mark.unit
    def test_register_plugin_succeeds(self, mock_channel_plugin_factory):
        """Successfully register plugin."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        plugin = mock_channel_plugin_factory(channel_id="test-channel")

        handle = registry.register(plugin)
        assert handle is not None
        assert registry.get("test-channel") is plugin

    @pytest.mark.unit
    def test_register_plugin_returns_handle(self, mock_channel_plugin_factory):
        """Registration returns handle for unregistration."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        plugin = mock_channel_plugin_factory(channel_id="test-channel")

        handle = registry.register(plugin)
        assert handle is not None
        assert isinstance(handle, str)

    @pytest.mark.unit
    def test_register_duplicate_channel_id_raises_error(
        self, mock_channel_plugin_factory
    ):
        """Duplicate channel_id raises ChannelAlreadyRegisteredError."""
        from app.channels.registry import ChannelAlreadyRegisteredError, ChannelRegistry

        registry = ChannelRegistry()
        plugin1 = mock_channel_plugin_factory(channel_id="duplicate")
        plugin2 = mock_channel_plugin_factory(channel_id="duplicate")

        registry.register(plugin1)
        with pytest.raises(ChannelAlreadyRegisteredError):
            registry.register(plugin2)

    @pytest.mark.unit
    def test_unregister_plugin_by_handle(self, mock_channel_plugin_factory):
        """Unregister using handle."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        plugin = mock_channel_plugin_factory(channel_id="test-channel")

        handle = registry.register(plugin)
        registry.unregister(handle=handle)

        assert registry.get("test-channel") is None

    @pytest.mark.unit
    def test_unregister_plugin_by_channel_id(self, mock_channel_plugin_factory):
        """Unregister using channel_id."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        plugin = mock_channel_plugin_factory(channel_id="test-channel")

        registry.register(plugin)
        registry.unregister(channel_id="test-channel")

        assert registry.get("test-channel") is None

    @pytest.mark.unit
    def test_unregister_nonexistent_raises_error(self):
        """Unknown plugin raises ChannelNotFoundError."""
        from app.channels.registry import ChannelNotFoundError, ChannelRegistry

        registry = ChannelRegistry()
        with pytest.raises(ChannelNotFoundError):
            registry.unregister(channel_id="nonexistent")


class TestChannelRegistryLifecycle:
    """Test lifecycle management."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_all_calls_start_on_each_plugin(
        self, mock_channel_plugin_factory
    ):
        """start_all() calls start() on each plugin."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        plugin1 = mock_channel_plugin_factory(channel_id="channel1")
        plugin2 = mock_channel_plugin_factory(channel_id="channel2")

        registry.register(plugin1)
        registry.register(plugin2)

        await registry.start_all()

        plugin1.start.assert_called_once()
        plugin2.start.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_all_respects_priority_order(self, mock_channel_plugin_factory):
        """Plugins started in priority order."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        start_order = []

        async def record_start_1():
            start_order.append("channel1")

        async def record_start_2():
            start_order.append("channel2")

        plugin1 = mock_channel_plugin_factory(channel_id="channel1")
        plugin1.start = AsyncMock(side_effect=record_start_1)

        plugin2 = mock_channel_plugin_factory(channel_id="channel2")
        plugin2.start = AsyncMock(side_effect=record_start_2)

        # Register with explicit priority
        registry.register(plugin1, priority=2)
        registry.register(plugin2, priority=1)

        await registry.start_all()

        # Priority 1 (channel2) should start before priority 2 (channel1)
        assert start_order == ["channel2", "channel1"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_all_calls_stop_on_each_plugin(
        self, mock_channel_plugin_factory
    ):
        """stop_all() calls stop() on each plugin."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        plugin1 = mock_channel_plugin_factory(channel_id="channel1")
        plugin2 = mock_channel_plugin_factory(channel_id="channel2")

        registry.register(plugin1)
        registry.register(plugin2)

        # Start first, then stop
        await registry.start_all()
        await registry.stop_all()

        plugin1.stop.assert_called_once()
        plugin2.stop.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_all_uses_reverse_order(self, mock_channel_plugin_factory):
        """Plugins stopped in reverse order (LIFO)."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        stop_order = []

        async def record_stop_1():
            stop_order.append("channel1")

        async def record_stop_2():
            stop_order.append("channel2")

        plugin1 = mock_channel_plugin_factory(channel_id="channel1")
        plugin1.stop = AsyncMock(side_effect=record_stop_1)

        plugin2 = mock_channel_plugin_factory(channel_id="channel2")
        plugin2.stop = AsyncMock(side_effect=record_stop_2)

        registry.register(plugin1, priority=1)
        registry.register(plugin2, priority=2)

        await registry.start_all()
        await registry.stop_all()

        # Should be reversed: channel2 (priority 2) stops before channel1 (priority 1)
        assert stop_order == ["channel2", "channel1"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_restart_plugin_by_channel_id(self, mock_channel_plugin_factory):
        """Restart specific plugin."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        plugin = mock_channel_plugin_factory(channel_id="test-channel")

        registry.register(plugin)
        await registry.start_all()

        # Reset mocks to track restart
        plugin.start.reset_mock()
        plugin.stop.reset_mock()

        await registry.restart("test-channel")

        plugin.stop.assert_called_once()
        plugin.start.assert_called_once()


class TestChannelRegistryStateManagement:
    """Test registry state."""

    @pytest.mark.unit
    def test_get_plugin_by_channel_id(self, mock_channel_plugin_factory):
        """Retrieve plugin by channel_id."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        plugin = mock_channel_plugin_factory(channel_id="test-channel")

        registry.register(plugin)
        retrieved = registry.get("test-channel")

        assert retrieved is plugin

    @pytest.mark.unit
    def test_get_all_registered_plugins(self, mock_channel_plugin_factory):
        """List all registered plugins."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        plugin1 = mock_channel_plugin_factory(channel_id="channel1")
        plugin2 = mock_channel_plugin_factory(channel_id="channel2")

        registry.register(plugin1)
        registry.register(plugin2)

        all_plugins = registry.get_all()
        assert len(all_plugins) == 2
        assert plugin1 in all_plugins
        assert plugin2 in all_plugins

    @pytest.mark.unit
    def test_get_plugin_status(self, mock_channel_plugin_factory):
        """Get status of specific plugin."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        plugin = mock_channel_plugin_factory(
            channel_id="test-channel", is_connected=True
        )

        registry.register(plugin)
        status = registry.get_status("test-channel")

        assert status is not None
        assert status["channel_id"] == "test-channel"
        assert status["is_connected"] is True

    @pytest.mark.unit
    def test_list_channel_ids(self, mock_channel_plugin_factory):
        """List all registered channel IDs."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        plugin1 = mock_channel_plugin_factory(channel_id="channel1")
        plugin2 = mock_channel_plugin_factory(channel_id="channel2")

        registry.register(plugin1)
        registry.register(plugin2)

        channel_ids = registry.list_channel_ids()
        assert set(channel_ids) == {"channel1", "channel2"}


class TestChannelRegistryErrorHandling:
    """Test error handling."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_plugin_start_failure_marks_unhealthy(
        self, mock_channel_plugin_factory
    ):
        """Failed start() marks plugin unhealthy."""
        from app.channels.registry import ChannelRegistry, ChannelStartupError

        registry = ChannelRegistry()
        plugin = mock_channel_plugin_factory(
            channel_id="failing-channel",
            start_side_effect=RuntimeError("Start failed"),
        )

        registry.register(plugin)

        # start_all raises ChannelStartupError by default
        with pytest.raises(ChannelStartupError):
            await registry.start_all()

        status = registry.get_status("failing-channel")
        assert status["healthy"] is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_one_failure_does_not_stop_others_with_continue_on_error(
        self, mock_channel_plugin_factory
    ):
        """One plugin failure doesn't prevent others with continue_on_error."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()

        plugin1 = mock_channel_plugin_factory(channel_id="good-channel")
        plugin2 = mock_channel_plugin_factory(
            channel_id="failing-channel",
            start_side_effect=RuntimeError("Start failed"),
        )
        plugin3 = mock_channel_plugin_factory(channel_id="another-good")

        registry.register(plugin1, priority=1)
        registry.register(plugin2, priority=2)
        registry.register(plugin3, priority=3)

        # With continue_on_error=True, should not raise
        errors = await registry.start_all(continue_on_error=True)

        assert len(errors) == 1
        plugin1.start.assert_called_once()
        plugin3.start.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_failure_logged_but_continues(self, mock_channel_plugin_factory):
        """stop() failures logged, other plugins still stopped."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        stop_order = []

        async def record_stop_1():
            stop_order.append("channel1")

        async def record_stop_2():
            stop_order.append("channel2")
            raise RuntimeError("Stop failed")

        async def record_stop_3():
            stop_order.append("channel3")

        plugin1 = mock_channel_plugin_factory(channel_id="channel1")
        plugin1.stop = AsyncMock(side_effect=record_stop_1)

        plugin2 = mock_channel_plugin_factory(channel_id="channel2")
        plugin2.stop = AsyncMock(side_effect=record_stop_2)

        plugin3 = mock_channel_plugin_factory(channel_id="channel3")
        plugin3.stop = AsyncMock(side_effect=record_stop_3)

        registry.register(plugin1, priority=1)
        registry.register(plugin2, priority=2)
        registry.register(plugin3, priority=3)

        await registry.start_all()
        await registry.stop_all()  # Should not raise

        # All stop methods should have been called despite plugin2 failure
        assert "channel1" in stop_order
        assert "channel2" in stop_order
        assert "channel3" in stop_order

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_timeout_handling(self, mock_channel_plugin_factory):
        """Plugin startup timeout should be handled."""
        from app.channels.registry import ChannelRegistry, ChannelStartupError

        registry = ChannelRegistry()

        async def slow_start():
            await asyncio.sleep(10)  # Very slow

        plugin = mock_channel_plugin_factory(channel_id="slow-channel")
        plugin.start = AsyncMock(side_effect=slow_start)

        registry.register(plugin)

        with pytest.raises(ChannelStartupError):
            await registry.start_all(timeout=0.1)


class TestChannelRegistryHealthChecks:
    """Test health check functionality."""

    @pytest.mark.unit
    def test_health_check_all_plugins(self, mock_channel_plugin_factory):
        """Run health checks on all plugins."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        plugin1 = mock_channel_plugin_factory(channel_id="channel1")
        plugin2 = mock_channel_plugin_factory(channel_id="channel2")

        registry.register(plugin1)
        registry.register(plugin2)

        health = registry.health_check_all()

        assert "channel1" in health
        assert "channel2" in health
        assert all(h.healthy for h in health.values())

    @pytest.mark.unit
    def test_health_check_specific_plugin(self, mock_channel_plugin_factory):
        """Run health check on specific plugin."""
        from app.channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        plugin = mock_channel_plugin_factory(channel_id="test-channel")
        plugin.health_check = MagicMock(
            return_value=HealthStatus(healthy=True, message="OK")
        )

        registry.register(plugin)
        status = registry.health_check("test-channel")

        assert status.healthy is True
        assert status.message == "OK"

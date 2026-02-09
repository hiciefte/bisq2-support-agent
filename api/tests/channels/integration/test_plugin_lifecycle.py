"""Integration tests for Plugin lifecycle.

Tests plugin startup/shutdown through registry.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import HealthStatus
from app.channels.registry import ChannelRegistry, ChannelStartupError


@pytest.fixture
def lifecycle_registry():
    """Registry for lifecycle testing."""
    return ChannelRegistry()


class TestPluginLifecycle:
    """Test plugin startup/shutdown."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_startup_initializes_all_channels(
        self, lifecycle_registry, mock_channel_plugin_factory
    ):
        """All enabled channels started."""
        plugin1 = mock_channel_plugin_factory(channel_id="web")
        plugin2 = mock_channel_plugin_factory(channel_id="matrix")
        plugin3 = mock_channel_plugin_factory(channel_id="bisq2")

        lifecycle_registry.register(plugin1)
        lifecycle_registry.register(plugin2)
        lifecycle_registry.register(plugin3)

        await lifecycle_registry.start_all()

        plugin1.start.assert_called_once()
        plugin2.start.assert_called_once()
        plugin3.start.assert_called_once()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_shutdown_cleans_up_all_channels(
        self, lifecycle_registry, mock_channel_plugin_factory
    ):
        """All channels properly stopped."""
        plugin1 = mock_channel_plugin_factory(channel_id="web", is_connected=True)
        plugin2 = mock_channel_plugin_factory(channel_id="matrix", is_connected=True)

        lifecycle_registry.register(plugin1)
        lifecycle_registry.register(plugin2)

        # Must start before stop (stop_all only stops started channels)
        await lifecycle_registry.start_all()

        await lifecycle_registry.stop_all()

        plugin1.stop.assert_called_once()
        plugin2.stop.assert_called_once()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_failed_startup_continues_with_others(
        self, lifecycle_registry, mock_channel_plugin_factory
    ):
        """Failed startup doesn't prevent other channels from starting."""
        # One plugin will fail
        failing_plugin = mock_channel_plugin_factory(
            channel_id="failing",
            start_side_effect=RuntimeError("Connection failed"),
        )
        working_plugin = mock_channel_plugin_factory(channel_id="working")

        lifecycle_registry.register(failing_plugin)
        lifecycle_registry.register(working_plugin)

        # With continue_on_error=True, should not raise
        errors = await lifecycle_registry.start_all(continue_on_error=True)

        # One error occurred
        assert len(errors) == 1
        # But working plugin was still started
        working_plugin.start.assert_called_once()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_startup_raises_on_failure_by_default(
        self, lifecycle_registry, mock_channel_plugin_factory
    ):
        """Failed startup raises by default."""
        failing_plugin = mock_channel_plugin_factory(
            channel_id="failing",
            start_side_effect=RuntimeError("Connection failed"),
        )

        lifecycle_registry.register(failing_plugin)

        with pytest.raises(ChannelStartupError):
            await lifecycle_registry.start_all()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_restart_stops_and_starts_plugin(
        self, lifecycle_registry, mock_channel_plugin_factory
    ):
        """Restart properly cycles plugin."""
        plugin = mock_channel_plugin_factory(channel_id="web", is_connected=True)
        lifecycle_registry.register(plugin)

        # Start first so restart has something to stop
        await lifecycle_registry.start_all()

        await lifecycle_registry.restart("web")

        # stop() called once during restart (not during initial start)
        # start() called twice: once during start_all, once during restart
        assert plugin.stop.call_count == 1
        assert plugin.start.call_count == 2

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_stop_failure_logged_but_continues(
        self, lifecycle_registry, mock_channel_plugin_factory
    ):
        """stop() failures logged, other plugins still stopped."""
        failing_plugin = mock_channel_plugin_factory(channel_id="failing")
        failing_plugin.stop = AsyncMock(side_effect=RuntimeError("Stop failed"))

        working_plugin = mock_channel_plugin_factory(channel_id="working")

        lifecycle_registry.register(failing_plugin)
        lifecycle_registry.register(working_plugin)

        # Must start before stop (stop_all only stops started channels)
        await lifecycle_registry.start_all()

        # Should not raise, just log and continue
        errors = await lifecycle_registry.stop_all()

        # Both were attempted
        failing_plugin.stop.assert_called_once()
        working_plugin.stop.assert_called_once()
        # One error returned
        assert len(errors) == 1

    @pytest.mark.integration
    def test_health_check_all_returns_all_statuses(
        self, lifecycle_registry, mock_channel_plugin_factory
    ):
        """Health check returns status for all registered channels."""
        healthy_plugin = mock_channel_plugin_factory(channel_id="healthy")
        healthy_plugin.health_check = MagicMock(return_value=HealthStatus(healthy=True))

        unhealthy_plugin = mock_channel_plugin_factory(channel_id="unhealthy")
        unhealthy_plugin.health_check = MagicMock(
            return_value=HealthStatus(healthy=False, details={"error": "disconnected"})
        )

        lifecycle_registry.register(healthy_plugin)
        lifecycle_registry.register(unhealthy_plugin)

        statuses = lifecycle_registry.health_check_all()

        assert "healthy" in statuses
        assert statuses["healthy"].healthy is True
        assert "unhealthy" in statuses
        assert statuses["unhealthy"].healthy is False

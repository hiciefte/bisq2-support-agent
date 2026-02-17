"""Tests for Channel Bootstrapper.

TDD tests for configuration-driven channel initialization.
"""

import importlib
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest
from app.channels.base import ChannelBase
from app.channels.models import ChannelCapability, ChannelType, OutgoingMessage


@pytest.fixture(autouse=True)
def restore_channel_types():
    """Restore global channel type registry after each test."""
    from app.channels.registry import _CHANNEL_TYPES

    snapshot = dict(_CHANNEL_TYPES)
    yield
    _CHANNEL_TYPES.clear()
    _CHANNEL_TYPES.update(snapshot)


# =============================================================================
# Test Channel Classes for Testing
# =============================================================================


class MockChannelForBootstrap(ChannelBase):
    """Mock channel for testing bootstrapper."""

    REQUIRED_PACKAGES: ClassVar[tuple[str, ...]] = ()

    @property
    def channel_id(self) -> str:
        return "mock"

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.WEB

    @property
    def capabilities(self) -> set:
        return {ChannelCapability.TEXT_MESSAGES}

    async def start(self) -> None:
        self._is_connected = True

    async def stop(self) -> None:
        self._is_connected = False

    async def send_message(self, target: str, message: OutgoingMessage) -> bool:
        return True

    def get_delivery_target(self, metadata):
        return ""

    def format_escalation_message(self, username, escalation_id, support_handle):
        return f"Escalated #{escalation_id}"


class MockChannelWithDeps(ChannelBase):
    """Mock channel with external dependencies."""

    REQUIRED_PACKAGES: ClassVar[tuple[str, ...]] = ("nonexistent_package",)

    @classmethod
    def setup_dependencies(cls, runtime: Any, settings: Any) -> None:
        """Register mock dependencies."""
        runtime.register("mock_client", MagicMock())

    @property
    def channel_id(self) -> str:
        return "mock_with_deps"

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.WEB

    @property
    def capabilities(self) -> set:
        return {ChannelCapability.TEXT_MESSAGES}

    async def start(self) -> None:
        self._is_connected = True

    async def stop(self) -> None:
        self._is_connected = False

    async def send_message(self, target: str, message: OutgoingMessage) -> bool:
        return True

    def get_delivery_target(self, metadata):
        return ""

    def format_escalation_message(self, username, escalation_id, support_handle):
        return f"Escalated #{escalation_id}"


# =============================================================================
# Tests for ChannelBase Setup Methods
# =============================================================================


class TestChannelBaseSetupMethods:
    """Test ChannelBase REQUIRED_PACKAGES and setup methods."""

    @pytest.mark.unit
    def test_required_packages_default_empty(self):
        """Default REQUIRED_PACKAGES is empty tuple."""
        from app.channels.base import ChannelBase

        assert hasattr(ChannelBase, "REQUIRED_PACKAGES")
        assert ChannelBase.REQUIRED_PACKAGES == ()

    @pytest.mark.unit
    def test_check_dependencies_returns_true_when_no_packages(self):
        """check_dependencies returns (True, []) when no packages required."""
        ok, missing = MockChannelForBootstrap.check_dependencies()
        assert ok is True
        assert missing == []

    @pytest.mark.unit
    def test_check_dependencies_returns_false_when_package_missing(self):
        """check_dependencies returns (False, [missing]) when package unavailable."""
        ok, missing = MockChannelWithDeps.check_dependencies()
        assert ok is False
        assert "nonexistent_package" in missing

    @pytest.mark.unit
    def test_check_dependencies_with_installed_package(self):
        """check_dependencies returns True for installed packages."""

        class ChannelWithInstalledPackage(MockChannelForBootstrap):
            REQUIRED_PACKAGES: ClassVar[tuple[str, ...]] = ("pytest",)

        ok, missing = ChannelWithInstalledPackage.check_dependencies()
        assert ok is True
        assert missing == []

    @pytest.mark.unit
    def test_setup_dependencies_default_is_noop(self):
        """Default setup_dependencies does nothing."""
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        settings = MagicMock()

        # Should not raise
        MockChannelForBootstrap.setup_dependencies(runtime, settings)

        # Should not have called register
        runtime.register.assert_not_called()

    @pytest.mark.unit
    def test_setup_dependencies_can_register_services(self):
        """setup_dependencies can register services in runtime."""
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        settings = MagicMock()

        MockChannelWithDeps.setup_dependencies(runtime, settings)

        # Verify register was called with correct service name
        runtime.register.assert_called_once()
        call_args = runtime.register.call_args
        assert call_args[0][0] == "mock_client"  # First positional arg is service name


# =============================================================================
# Tests for @register_channel Decorator
# =============================================================================


class TestRegisterChannelDecorator:
    """Test @register_channel type registration."""

    @pytest.mark.unit
    def test_register_channel_adds_to_registry(self):
        """@register_channel adds class to type registry."""
        from app.channels.registry import (
            _CHANNEL_TYPES,
            get_registered_channel_types,
            register_channel,
        )

        # Clear any existing registration for this test
        _CHANNEL_TYPES.pop("test_channel", None)

        @register_channel("test_channel")
        class TestChannel(ChannelBase):
            @property
            def channel_id(self) -> str:
                return "test_channel"

            @property
            def channel_type(self) -> ChannelType:
                return ChannelType.WEB

            @property
            def capabilities(self) -> set:
                return set()

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

            async def send_message(self, target, message) -> bool:
                return True

            def get_delivery_target(self, metadata):
                return ""

            def format_escalation_message(
                self, username, escalation_id, support_handle
            ):
                return f"Escalated #{escalation_id}"

        types = get_registered_channel_types()
        assert "test_channel" in types
        assert types["test_channel"] is TestChannel

    @pytest.mark.unit
    def test_get_registered_channel_types_returns_copy(self):
        """get_registered_channel_types returns a copy, not the original."""
        from app.channels.registry import _CHANNEL_TYPES, get_registered_channel_types

        types = get_registered_channel_types()
        types["fake"] = MagicMock()

        # Original should not be modified
        assert "fake" not in _CHANNEL_TYPES


# =============================================================================
# Tests for ChannelBootstrapper
# =============================================================================


class TestChannelBootstrapper:
    """Test ChannelBootstrapper initialization."""

    @pytest.mark.unit
    def test_bootstrapper_creates_runtime(self):
        """Bootstrapper creates ChannelRuntime with settings and rag_service."""
        from app.channels.bootstrapper import ChannelBootstrapper

        settings = MagicMock()
        rag_service = MagicMock()

        bootstrapper = ChannelBootstrapper(settings, rag_service)
        assert bootstrapper.settings is settings
        assert bootstrapper.rag_service is rag_service

    @pytest.mark.unit
    def test_bootstrap_result_contains_runtime_and_registry(self):
        """bootstrap() returns BootstrapResult with runtime and registry."""
        from app.channels.bootstrapper import ChannelBootstrapper

        settings = MagicMock()
        settings.CHANNEL_PLUGINS = []  # No plugins to load
        settings.WEB_CHANNEL_ENABLED = False
        settings.MATRIX_SYNC_ENABLED = False
        settings.BISQ2_CHANNEL_ENABLED = False

        rag_service = MagicMock()

        bootstrapper = ChannelBootstrapper(settings, rag_service)
        result = bootstrapper.bootstrap()

        assert result.runtime is not None
        assert result.registry is not None
        assert isinstance(result.loaded, list)
        assert isinstance(result.skipped, list)
        assert isinstance(result.errors, list)

    @pytest.mark.unit
    def test_matrix_sync_enabled_flag_enables_matrix_channel(self):
        """MATRIX_SYNC_ENABLED should enable matrix channel loading."""
        from app.channels.bootstrapper import ChannelBootstrapper

        settings = MagicMock()
        settings.CHANNEL_PLUGINS = []
        settings.WEB_CHANNEL_ENABLED = False
        settings.MATRIX_SYNC_ENABLED = True
        settings.BISQ2_CHANNEL_ENABLED = False

        rag_service = MagicMock()

        bootstrapper = ChannelBootstrapper(settings, rag_service)
        enabled = bootstrapper._get_enabled_channels()

        assert "matrix" in enabled

    @pytest.mark.unit
    def test_bootstrap_loads_enabled_channels(self):
        """bootstrap() loads channels that are enabled in config."""
        from app.channels.bootstrapper import ChannelBootstrapper
        from app.channels.registry import _CHANNEL_TYPES

        # Register a test channel type
        _CHANNEL_TYPES["test_enabled"] = MockChannelForBootstrap

        settings = MagicMock()
        settings.CHANNEL_PLUGINS = []
        settings.WEB_CHANNEL_ENABLED = False
        settings.MATRIX_SYNC_ENABLED = False
        settings.BISQ2_CHANNEL_ENABLED = False
        # Simulate test_enabled being enabled
        settings.TEST_ENABLED_CHANNEL_ENABLED = True

        rag_service = MagicMock()

        # Patch _get_enabled_channels to return our test channel
        bootstrapper = ChannelBootstrapper(settings, rag_service)
        bootstrapper._get_enabled_channels = MagicMock(return_value=["test_enabled"])

        result = bootstrapper.bootstrap()

        assert "test_enabled" in result.loaded
        assert len(result.errors) == 0

    @pytest.mark.unit
    def test_bootstrap_skips_unregistered_channels(self):
        """bootstrap() skips channels that have no registered class."""
        from app.channels.bootstrapper import ChannelBootstrapper

        settings = MagicMock()
        settings.CHANNEL_PLUGINS = []
        settings.WEB_CHANNEL_ENABLED = False
        settings.MATRIX_SYNC_ENABLED = False
        settings.BISQ2_CHANNEL_ENABLED = False

        rag_service = MagicMock()

        bootstrapper = ChannelBootstrapper(settings, rag_service)
        # Request a channel that doesn't exist
        bootstrapper._get_enabled_channels = MagicMock(
            return_value=["nonexistent_channel"]
        )

        result = bootstrapper.bootstrap()

        assert "nonexistent_channel" in result.skipped
        assert "nonexistent_channel" not in result.loaded

    @pytest.mark.unit
    def test_bootstrap_calls_setup_dependencies(self):
        """bootstrap() calls setup_dependencies for each channel."""
        from app.channels.bootstrapper import ChannelBootstrapper
        from app.channels.registry import _CHANNEL_TYPES

        # Create a channel class with mocked setup_dependencies
        class ChannelWithMockedSetup(MockChannelForBootstrap):
            setup_called = False

            @classmethod
            def setup_dependencies(cls, runtime, settings):
                cls.setup_called = True

        _CHANNEL_TYPES["setup_test"] = ChannelWithMockedSetup

        settings = MagicMock()
        settings.CHANNEL_PLUGINS = []
        rag_service = MagicMock()

        bootstrapper = ChannelBootstrapper(settings, rag_service)
        bootstrapper._get_enabled_channels = MagicMock(return_value=["setup_test"])

        result = bootstrapper.bootstrap()

        assert ChannelWithMockedSetup.setup_called is True
        assert "setup_test" in result.loaded

    @pytest.mark.unit
    def test_bootstrap_handles_setup_failure(self):
        """bootstrap() handles exceptions in setup_dependencies gracefully."""
        from app.channels.bootstrapper import ChannelBootstrapper
        from app.channels.registry import _CHANNEL_TYPES

        class ChannelWithFailingSetup(MockChannelForBootstrap):
            @classmethod
            def setup_dependencies(cls, runtime, settings):
                raise RuntimeError("Setup failed")

        _CHANNEL_TYPES["failing_setup"] = ChannelWithFailingSetup

        settings = MagicMock()
        settings.CHANNEL_PLUGINS = []
        rag_service = MagicMock()

        bootstrapper = ChannelBootstrapper(settings, rag_service)
        bootstrapper._get_enabled_channels = MagicMock(return_value=["failing_setup"])

        result = bootstrapper.bootstrap()

        # Should have an error for this channel
        assert len(result.errors) == 1
        assert result.errors[0][0] == "failing_setup"
        assert "failing_setup" not in result.loaded

    @pytest.mark.unit
    def test_bootstrap_imports_channel_modules(self):
        """bootstrap() imports modules from CHANNEL_PLUGINS config."""
        from app.channels.bootstrapper import ChannelBootstrapper

        settings = MagicMock()
        settings.CHANNEL_PLUGINS = ["os", "sys"]  # Use stdlib modules for test
        settings.WEB_CHANNEL_ENABLED = False
        settings.MATRIX_SYNC_ENABLED = False
        settings.BISQ2_CHANNEL_ENABLED = False

        rag_service = MagicMock()

        with patch.object(importlib, "import_module") as mock_import:
            bootstrapper = ChannelBootstrapper(settings, rag_service)
            bootstrapper.bootstrap()

            # Should have tried to import the modules
            assert mock_import.call_count >= 2


# =============================================================================
# Tests for BootstrapResult
# =============================================================================


class TestBootstrapResult:
    """Test BootstrapResult dataclass."""

    @pytest.mark.unit
    def test_bootstrap_result_fields(self):
        """BootstrapResult has expected fields."""
        from app.channels.bootstrapper import BootstrapResult
        from app.channels.registry import ChannelRegistry
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        registry = MagicMock(spec=ChannelRegistry)

        result = BootstrapResult(
            runtime=runtime,
            registry=registry,
            loaded=["web", "matrix"],
            skipped=["bisq2"],
            errors=[("slack", RuntimeError("test"))],
        )

        assert result.runtime is runtime
        assert result.registry is registry
        assert result.loaded == ["web", "matrix"]
        assert result.skipped == ["bisq2"]
        assert len(result.errors) == 1

    @pytest.mark.unit
    def test_bootstrap_result_default_lists(self):
        """BootstrapResult has empty default lists."""
        from app.channels.bootstrapper import BootstrapResult
        from app.channels.registry import ChannelRegistry
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        registry = MagicMock(spec=ChannelRegistry)

        result = BootstrapResult(runtime=runtime, registry=registry)

        assert result.loaded == []
        assert result.skipped == []
        assert result.errors == []

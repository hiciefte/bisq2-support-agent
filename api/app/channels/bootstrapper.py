"""Configuration-driven channel initialization.

Provides ChannelBootstrapper for automated channel loading based on configuration.
"""

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, List, Tuple

from app.channels.registry import ChannelRegistry, get_registered_channel_types
from app.channels.runtime import ChannelRuntime

logger = logging.getLogger(__name__)


@dataclass
class BootstrapResult:
    """Result of channel bootstrapping.

    Attributes:
        runtime: The ChannelRuntime with registered services.
        registry: The ChannelRegistry with instantiated channels.
        loaded: List of channel IDs that were successfully loaded.
        skipped: List of channel IDs that were skipped (no class registered).
        errors: List of (channel_id, exception) tuples for failed channels.
    """

    runtime: ChannelRuntime
    registry: ChannelRegistry
    loaded: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: List[Tuple[str, Exception]] = field(default_factory=list)


class ChannelBootstrapper:
    """Configuration-driven channel initialization.

    Automates the process of:
    1. Importing channel modules to trigger @register_channel decorators
    2. Creating ChannelRuntime with core services
    3. Calling setup_dependencies() for each enabled channel
    4. Instantiating and registering channels in ChannelRegistry

    Example:
        bootstrapper = ChannelBootstrapper(settings, rag_service)
        result = bootstrapper.bootstrap()

        if result.errors:
            for channel_id, error in result.errors:
                logger.error(f"Channel '{channel_id}' failed: {error}")

        await result.registry.start_all()

    Attributes:
        settings: Application settings object.
        rag_service: RAG service for query processing.
    """

    def __init__(self, settings: Any, rag_service: Any) -> None:
        """Initialize bootstrapper.

        Args:
            settings: Application settings object.
            rag_service: RAG service for query processing.
        """
        self.settings = settings
        self.rag_service = rag_service

    def bootstrap(self) -> BootstrapResult:
        """Initialize all enabled channels.

        Process:
        1. Import channel modules (triggers @register_channel decorators)
        2. Create runtime with core services
        3. For each enabled channel:
           - Check package dependencies (warning if missing)
           - Call setup_dependencies()
           - Instantiate channel
           - Register in registry
        4. Return result with loaded/skipped/errors

        Returns:
            BootstrapResult with runtime, registry, and status information.
        """
        result = BootstrapResult(
            runtime=self._create_runtime(),
            registry=ChannelRegistry(),
        )

        # Import channel modules from config
        self._import_channel_modules()

        # Get enabled channels from config
        enabled = self._get_enabled_channels()
        channel_types = get_registered_channel_types()

        for channel_id in enabled:
            try:
                channel_class = channel_types.get(channel_id)
                if not channel_class:
                    logger.warning(
                        f"No class registered for channel '{channel_id}'. "
                        f"Ensure the channel module is in CHANNEL_PLUGINS."
                    )
                    result.skipped.append(channel_id)
                    continue

                # Check package dependencies
                ok, missing = channel_class.check_dependencies()
                if not ok:
                    logger.warning(
                        f"Channel '{channel_id}' missing packages: {missing}. "
                        f"Channel may run in degraded mode."
                    )

                # Setup channel-specific dependencies
                logger.debug(f"Setting up dependencies for channel '{channel_id}'")
                channel_class.setup_dependencies(result.runtime, self.settings)

                # Create and register instance
                channel = channel_class(result.runtime)
                result.registry.register(channel)
                result.loaded.append(channel_id)

                logger.info(f"Channel '{channel_id}' loaded successfully")

            except Exception as e:
                logger.error(f"Failed to load channel '{channel_id}': {e}")
                result.errors.append((channel_id, e))

        # Log summary
        logger.info(
            f"Channel bootstrap complete: "
            f"{len(result.loaded)} loaded, "
            f"{len(result.skipped)} skipped, "
            f"{len(result.errors)} errors"
        )

        return result

    def _create_runtime(self) -> ChannelRuntime:
        """Create runtime with core services.

        Returns:
            ChannelRuntime configured with settings and RAG service.
        """
        return ChannelRuntime(
            settings=self.settings,
            rag_service=self.rag_service,
        )

    def _import_channel_modules(self) -> None:
        """Import channel modules to trigger @register_channel decorators.

        Reads module paths from settings.CHANNEL_PLUGINS or uses defaults.
        """
        modules = getattr(
            self.settings,
            "CHANNEL_PLUGINS",
            [
                "app.channels.plugins.web.channel",
                "app.channels.plugins.matrix.channel",
                "app.channels.plugins.bisq2.channel",
            ],
        )

        for module_path in modules:
            try:
                importlib.import_module(module_path)
                logger.debug(f"Imported channel module: {module_path}")
            except ImportError as e:
                logger.warning(f"Could not import channel module '{module_path}': {e}")

    def _get_enabled_channels(self) -> List[str]:
        """Get list of enabled channel IDs from config.

        Returns:
            List of channel ID strings that should be loaded.
        """
        enabled = []

        # Check standard channel enable flags
        if getattr(self.settings, "WEB_CHANNEL_ENABLED", True):
            enabled.append("web")

        if getattr(self.settings, "MATRIX_ENABLED", False):
            enabled.append("matrix")

        if getattr(self.settings, "BISQ2_CHANNEL_ENABLED", False):
            enabled.append("bisq2")

        return enabled

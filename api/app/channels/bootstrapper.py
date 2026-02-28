"""Configuration-driven channel initialization.

Provides ChannelBootstrapper for automated channel loading based on configuration.
"""

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

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

    def __init__(
        self,
        settings: Any,
        rag_service: Any,
        shared_services: Dict[str, Any] | None = None,
    ) -> None:
        """Initialize bootstrapper.

        Args:
            settings: Application settings object.
            rag_service: RAG service for query processing.
        """
        self.settings = settings
        self.rag_service = rag_service
        self.shared_services = dict(shared_services or {})

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
        self._wire_feedback_followup_coordinator(result.runtime, result.registry)

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
                result.runtime.register(
                    f"{channel_id}_channel",
                    channel,
                    allow_override=True,
                )
                result.loaded.append(channel_id)

                logger.info(f"Channel '{channel_id}' loaded successfully")

            except Exception as e:
                logger.exception(f"Failed to load channel '{channel_id}'")
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
        runtime = ChannelRuntime(
            settings=self.settings,
            rag_service=self.rag_service,
        )
        for name, service in self.shared_services.items():
            if service is None:
                continue
            runtime.register(name, service, allow_override=True)

        # Register shared reaction services
        self._register_reaction_services(runtime)
        self._register_question_prefilter(runtime)

        return runtime

    def _register_reaction_services(self, runtime: ChannelRuntime) -> None:
        """Register SentMessageTracker and ReactionProcessor in runtime."""
        from app.channels.reactions import ReactionProcessor, SentMessageTracker

        tracker = SentMessageTracker()
        runtime.register("sent_message_tracker", tracker)

        # Ensure feedback_service is available on runtime (singleton pattern)
        if runtime.feedback_service is None:
            try:
                from app.services.feedback_service import FeedbackService

                runtime.feedback_service = FeedbackService()
            except Exception:
                logger.warning(
                    "Could not initialize FeedbackService for reaction processor"
                )

        salt = getattr(self.settings, "REACTOR_IDENTITY_SALT", "")
        processor = ReactionProcessor(
            tracker=tracker,
            feedback_service=runtime.feedback_service,
            reactor_identity_salt=salt,
            auto_escalation_delay_seconds=getattr(
                self.settings,
                "REACTION_NEGATIVE_STABILIZATION_SECONDS",
                20.0,
            ),
        )
        runtime.register("reaction_processor", processor)

        logger.debug("Registered reaction services (tracker + processor)")

    def _wire_feedback_followup_coordinator(
        self,
        runtime: ChannelRuntime,
        registry: ChannelRegistry,
    ) -> None:
        """Wire shared reaction-followup coordinator against channel registry."""
        try:
            from app.channels.feedback_followup import FeedbackFollowupCoordinator
        except ImportError:
            logger.debug("FeedbackFollowupCoordinator unavailable", exc_info=True)
            return

        coordinator = FeedbackFollowupCoordinator(
            feedback_service=runtime.feedback_service,
            channel_registry=registry,
            ttl_seconds=getattr(
                self.settings,
                "REACTION_FEEDBACK_FOLLOWUP_TTL_SECONDS",
                900.0,
            ),
        )
        runtime.register(
            "feedback_followup_coordinator",
            coordinator,
            allow_override=True,
        )
        processor = runtime.resolve_optional("reaction_processor")
        if processor is not None:
            processor.followup_coordinator = coordinator
        logger.debug("Wired feedback follow-up coordinator")

    @staticmethod
    def _register_question_prefilter(runtime: ChannelRuntime) -> None:
        """Register shared question prefilter for channel-side RAG gating."""
        from app.channels.question_prefilter import QuestionPrefilter

        runtime.register("question_prefilter", QuestionPrefilter())
        logger.debug("Registered question prefilter service")

    def _import_channel_modules(self) -> None:
        """Import channel modules to trigger @register_channel decorators.

        Reads module paths from settings.CHANNEL_PLUGINS or uses defaults.
        """
        default_modules = [
            "app.channels.plugins.web.channel",
            "app.channels.plugins.matrix.channel",
            "app.channels.plugins.bisq2.channel",
        ]
        modules = getattr(self.settings, "CHANNEL_PLUGINS", default_modules)

        if modules == default_modules:
            logger.debug(
                "CHANNEL_PLUGINS not configured, using default channel module list"
            )

        for module_path in modules:
            try:
                importlib.import_module(module_path)
                logger.debug(f"Imported channel module: {module_path}")
            except ImportError as e:
                logger.warning(f"Could not import channel module '{module_path}': {e}")

    @staticmethod
    def _as_bool(value: Any, default: bool) -> bool:
        """Coerce common env-style bool values while tolerating MagicMock objects."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        return default

    def _get_enabled_channels(self) -> List[str]:
        """Get list of enabled channel IDs from config.

        Returns:
            List of channel ID strings that should be loaded.
        """
        channel_types = get_registered_channel_types()
        if not channel_types:
            default_enabled_channels = []
            if self._as_bool(
                getattr(self.settings, "WEB_CHANNEL_ENABLED", True),
                default=True,
            ):
                default_enabled_channels.append("web")
            if self._as_bool(
                getattr(self.settings, "MATRIX_SYNC_ENABLED", False),
                default=False,
            ):
                default_enabled_channels.append("matrix")
            if self._as_bool(
                getattr(self.settings, "BISQ2_CHANNEL_ENABLED", False),
                default=False,
            ):
                default_enabled_channels.append("bisq2")
            return default_enabled_channels

        enabled: List[str] = []
        for channel_id, channel_class in sorted(channel_types.items()):
            enabled_flag = getattr(channel_class, "ENABLED_FLAG", None)
            default_enabled = bool(getattr(channel_class, "ENABLED_DEFAULT", False))
            if not isinstance(enabled_flag, str) or not enabled_flag.strip():
                enabled_flag = f"{channel_id.upper()}_CHANNEL_ENABLED"
            is_enabled = self._as_bool(
                getattr(self.settings, enabled_flag, default_enabled),
                default=default_enabled,
            )
            if is_enabled:
                enabled.append(channel_id)
        return enabled

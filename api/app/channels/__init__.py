"""Channel plugin architecture for multi-channel RAG system.

This package provides:
- ChannelBase: Abstract base class for channel plugins
- ChannelRegistry: Plugin registration and lifecycle management
- ChannelRuntime: Dependency injection container
- Security utilities: PII detection, rate limiting, authentication
- Message models: IncomingMessage, OutgoingMessage, etc.

Example usage:
    from app.channels import ChannelBase, ChannelRegistry, ChannelRuntime

    # Create runtime
    runtime = ChannelRuntime(settings=settings, rag_service=rag)

    # Create registry
    registry = ChannelRegistry()

    # Register channels
    registry.register(WebChannel(runtime))
    registry.register(MatrixChannel(runtime))

    # Start all channels
    await registry.start_all()
"""

from app.channels.base import ChannelBase, ChannelProtocol
from app.channels.bootstrapper import BootstrapResult, ChannelBootstrapper
from app.channels.config import (
    Bisq2ChannelConfig,
    ChannelConfigBase,
    ChannelsConfig,
    MatrixChannelConfig,
    WebChannelConfig,
)
from app.channels.dependencies import get_gateway
from app.channels.gateway import ChannelGateway
from app.channels.hooks import (
    BasePostProcessingHook,
    BasePreProcessingHook,
    HookPriority,
    PostProcessingHook,
    PreProcessingHook,
)
from app.channels.lifecycle import channel_lifespan, create_channel_gateway
from app.channels.models import (
    ChannelCapability,
    ChannelType,
    ChatMessage,
    DocumentReference,
    ErrorCode,
    GatewayError,
    HealthStatus,
    IncomingMessage,
    MessagePriority,
    OutgoingMessage,
    ResponseMetadata,
    UserContext,
)
from app.channels.registry import (
    ChannelAlreadyRegisteredError,
    ChannelNotFoundError,
    ChannelRegistry,
    ChannelStartupError,
    get_registered_channel_types,
    register_channel,
)
from app.channels.runtime import (
    ChannelRuntime,
    ServiceAlreadyRegisteredError,
    ServiceNotFoundError,
)
from app.channels.security import (
    EnvironmentSecretStore,
    ErrorFactory,
    InputValidator,
    PIIDetector,
    PIIType,
    RateLimitConfig,
    SecurityIncidentHandler,
    SecurityIncidentType,
    SensitiveDataFilter,
    TokenBucket,
)

__all__ = [
    # Base classes
    "ChannelBase",
    "ChannelProtocol",
    # Configuration
    "Bisq2ChannelConfig",
    "ChannelConfigBase",
    "ChannelsConfig",
    "MatrixChannelConfig",
    "WebChannelConfig",
    # Registry
    "ChannelRegistry",
    "ChannelAlreadyRegisteredError",
    "ChannelNotFoundError",
    "ChannelStartupError",
    "register_channel",
    "get_registered_channel_types",
    # Bootstrapper
    "BootstrapResult",
    "ChannelBootstrapper",
    # Runtime
    "ChannelRuntime",
    "ServiceAlreadyRegisteredError",
    "ServiceNotFoundError",
    # Models
    "ChannelCapability",
    "ChannelType",
    "ChatMessage",
    "DocumentReference",
    "ErrorCode",
    "GatewayError",
    "HealthStatus",
    "IncomingMessage",
    "MessagePriority",
    "OutgoingMessage",
    "ResponseMetadata",
    "UserContext",
    # Security
    "EnvironmentSecretStore",
    "ErrorFactory",
    "InputValidator",
    "PIIDetector",
    "PIIType",
    "RateLimitConfig",
    "SecurityIncidentHandler",
    "SecurityIncidentType",
    "SensitiveDataFilter",
    "TokenBucket",
    # Gateway
    "ChannelGateway",
    # Hooks
    "BasePostProcessingHook",
    "BasePreProcessingHook",
    "HookPriority",
    "PostProcessingHook",
    "PreProcessingHook",
    # Dependencies
    "get_gateway",
    # Lifecycle
    "channel_lifespan",
    "create_channel_gateway",
]

"""Channel configuration models.

Pydantic models for channel-specific configuration with validation.
"""

from typing import Dict, Optional

from pydantic import BaseModel, Field, SecretStr, model_validator

# =============================================================================
# Base Configuration
# =============================================================================


class ChannelConfigBase(BaseModel):
    """Base configuration for all channels."""

    enabled: bool = True
    rate_limit_per_minute: int = Field(default=60, ge=1, le=1000)
    max_message_bytes: int = Field(default=4096, ge=100, le=65536)


# =============================================================================
# Reaction Configuration
# =============================================================================


class ReactionConfig(BaseModel):
    """Configuration for reaction-based feedback collection."""

    enabled: bool = Field(
        default=False, description="Enable reaction feedback for this channel"
    )
    emoji_rating_map: Optional[Dict[str, int]] = Field(
        default=None, description="Custom emoji-to-rating map (0=negative, 1=positive)"
    )
    message_tracking_ttl_hours: int = Field(
        default=24, ge=1, le=168, description="TTL for sent message tracking (hours)"
    )
    reactor_identity_salt: SecretStr = Field(
        default=SecretStr(""),
        description="Salt for reactor identity hashing (must be stable across deployments)",
    )

    @model_validator(mode="after")
    def validate_salt_when_enabled(self) -> "ReactionConfig":
        """Ensure a non-empty salt is provided when reactions are enabled."""
        if self.enabled and not self.reactor_identity_salt.get_secret_value():
            raise ValueError(
                "reactor_identity_salt must be set when reactions are enabled"
            )
        return self


# =============================================================================
# Channel-Specific Configurations
# =============================================================================

# Channel-specific configs live in their domain modules
from app.channels.plugins.bisq2.config import Bisq2ChannelConfig  # noqa: E402
from app.channels.plugins.matrix.config import MatrixChannelConfig  # noqa: E402
from app.channels.plugins.web.config import WebChannelConfig  # noqa: E402

# =============================================================================
# Aggregate Configuration
# =============================================================================


class ChannelsConfig(BaseModel):
    """Aggregate channel configuration."""

    bisq2: Bisq2ChannelConfig = Field(default_factory=Bisq2ChannelConfig)
    web: WebChannelConfig = Field(default_factory=WebChannelConfig)
    matrix: MatrixChannelConfig = Field(default_factory=MatrixChannelConfig)

    @model_validator(mode="after")
    def validate_at_least_one_enabled(self) -> "ChannelsConfig":
        """Ensure at least one channel is enabled."""
        enabled = [
            name
            for name, config in [
                ("bisq2", self.bisq2),
                ("web", self.web),
                ("matrix", self.matrix),
            ]
            if config.enabled
        ]
        if not enabled:
            raise ValueError("At least one channel must be enabled")
        return self

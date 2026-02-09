"""Channel configuration models.

Pydantic models for channel-specific configuration with validation.
"""

from typing import List

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
# Channel-Specific Configurations
# =============================================================================


class Bisq2ChannelConfig(ChannelConfigBase):
    """Bisq2 native support chat configuration."""

    api_url: str = "http://bisq2-api:8090"
    poll_interval_seconds: int = Field(default=60, ge=10, le=3600)
    export_batch_size: int = Field(default=100, ge=10, le=1000)

    @model_validator(mode="after")
    def validate_api_url(self) -> "Bisq2ChannelConfig":
        """Validate API URL is set when enabled."""
        if self.enabled and not self.api_url:
            raise ValueError("Bisq2 enabled but api_url not set")
        return self


class WebChannelConfig(ChannelConfigBase):
    """Web chat configuration."""

    cors_origins: List[str] = Field(default_factory=list)
    max_chat_history: int = Field(default=10, ge=0, le=50)


class MatrixChannelConfig(ChannelConfigBase):
    """Matrix channel configuration."""

    enabled: bool = False  # Disabled by default
    homeserver_url: str = ""
    user_id: str = ""
    password: SecretStr = SecretStr("")
    rooms: List[str] = Field(default_factory=list)
    session_file: str = "matrix_session.json"
    poll_interval_seconds: int = Field(default=5, ge=1, le=60)

    @model_validator(mode="after")
    def validate_auth_config(self) -> "MatrixChannelConfig":
        """Validate required fields when Matrix is enabled."""
        if self.enabled:
            if not self.homeserver_url:
                raise ValueError("Matrix enabled but homeserver_url not set")
            if not self.user_id:
                raise ValueError("Matrix enabled but user_id not set")
            if not self.rooms:
                raise ValueError("Matrix enabled but no rooms configured")
            for room in self.rooms:
                if not room.startswith("!"):
                    raise ValueError(f"Invalid room ID format: {room}")
        return self


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

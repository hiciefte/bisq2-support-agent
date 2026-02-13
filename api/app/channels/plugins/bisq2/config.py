"""Bisq2 channel configuration."""

from app.channels.config import ChannelConfigBase, ReactionConfig
from pydantic import Field, model_validator


class Bisq2ChannelConfig(ChannelConfigBase):
    """Bisq2 native support chat configuration."""

    api_url: str = "http://bisq2-api:8090"
    poll_interval_seconds: int = Field(default=60, ge=10, le=3600)
    export_batch_size: int = Field(default=100, ge=10, le=1000)
    reactions: ReactionConfig = Field(default_factory=ReactionConfig)

    @model_validator(mode="after")
    def validate_api_url(self) -> "Bisq2ChannelConfig":
        """Validate API URL is set when enabled."""
        if self.enabled and not self.api_url:
            raise ValueError("Bisq2 enabled but api_url not set")
        return self

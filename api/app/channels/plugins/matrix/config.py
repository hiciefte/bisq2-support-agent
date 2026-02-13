"""Matrix channel configuration."""

from typing import List

from app.channels.config import ChannelConfigBase, ReactionConfig
from pydantic import Field, SecretStr, model_validator


class MatrixChannelConfig(ChannelConfigBase):
    """Matrix channel configuration."""

    enabled: bool = False  # Disabled by default
    homeserver_url: str = ""
    user_id: str = ""
    password: SecretStr = SecretStr("")
    rooms: List[str] = Field(default_factory=list)
    session_file: str = "matrix_session.json"
    poll_interval_seconds: int = Field(default=5, ge=1, le=60)
    reactions: ReactionConfig = Field(default_factory=ReactionConfig)

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

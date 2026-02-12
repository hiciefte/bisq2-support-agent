"""Web channel configuration."""

from typing import List

from app.channels.config import ChannelConfigBase
from pydantic import Field


class WebChannelConfig(ChannelConfigBase):
    """Web chat configuration."""

    cors_origins: List[str] = Field(default_factory=list)
    max_chat_history: int = Field(default=10, ge=0, le=50)

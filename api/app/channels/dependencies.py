"""FastAPI dependencies for Channel Gateway.

Provides dependency injection for channel gateway in routes.
"""

import logging

from app.channels.gateway import ChannelGateway
from fastapi import Request

logger = logging.getLogger(__name__)


def get_gateway(request: Request) -> ChannelGateway:
    """Get channel gateway from app state.

    Args:
        request: FastAPI request object.

    Returns:
        ChannelGateway instance from app.state.

    Raises:
        RuntimeError: If gateway not initialized.
    """
    if not hasattr(request.app.state, "channel_gateway"):
        raise RuntimeError("Gateway not initialized")

    return request.app.state.channel_gateway

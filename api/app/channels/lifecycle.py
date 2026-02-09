"""Channel Gateway Lifecycle Management.

Provides lifecycle management for channel gateway initialization
and cleanup during FastAPI application lifespan.
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from app.channels.gateway import ChannelGateway, RAGServiceProtocol
from app.channels.middleware import (
    AuthenticationHook,
    MetricsHook,
    PIIFilterHook,
    RateLimitHook,
)
from fastapi import FastAPI

logger = logging.getLogger(__name__)


def create_channel_gateway(
    rag_service: RAGServiceProtocol,
    register_default_hooks: bool = False,
    rate_limit_capacity: int = 20,
    rate_limit_refill_rate: float = 1.0,
) -> ChannelGateway:
    """Create and configure channel gateway.

    Args:
        rag_service: RAG service for query processing.
        register_default_hooks: Whether to register default middleware hooks.
        rate_limit_capacity: Token bucket capacity for rate limiting.
        rate_limit_refill_rate: Token refill rate per second.

    Returns:
        Configured ChannelGateway instance.
    """
    gateway = ChannelGateway(rag_service=rag_service)

    if register_default_hooks:
        # Register pre-processing hooks
        gateway.register_pre_hook(
            RateLimitHook(
                capacity=rate_limit_capacity,
                refill_rate=rate_limit_refill_rate,
            )
        )
        gateway.register_pre_hook(AuthenticationHook())
        gateway.register_pre_hook(MetricsHook())

        # Register post-processing hooks
        gateway.register_post_hook(PIIFilterHook())

        logger.info("Registered default gateway hooks")

    return gateway


@asynccontextmanager
async def channel_lifespan(
    app: FastAPI,
    rag_service: Optional[RAGServiceProtocol] = None,
    register_default_hooks: bool = True,
):
    """Async context manager for channel gateway lifecycle.

    Usage in main.py:
        async with channel_lifespan(app, rag_service):
            yield

    Args:
        app: FastAPI application instance.
        rag_service: RAG service for query processing.
            If None, will attempt to get from app.state.rag_service.
        register_default_hooks: Whether to register default middleware hooks.

    Yields:
        None
    """
    # Get RAG service from app.state if not provided
    if rag_service is None:
        if hasattr(app.state, "rag_service"):
            rag_service = app.state.rag_service
        else:
            logger.warning("No RAG service available, gateway will not be initialized")
            yield
            return

    # Create and store gateway
    gateway = create_channel_gateway(
        rag_service=rag_service,
        register_default_hooks=register_default_hooks,
    )
    app.state.channel_gateway = gateway

    logger.info("Channel gateway initialized")

    try:
        yield
    finally:
        # Cleanup
        if hasattr(app.state, "channel_gateway"):
            del app.state.channel_gateway
            logger.info("Channel gateway cleaned up")

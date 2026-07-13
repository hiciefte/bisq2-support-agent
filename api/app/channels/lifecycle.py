"""Channel Gateway Lifecycle Management.

Provides lifecycle management for channel gateway initialization
and cleanup during FastAPI application lifespan.
"""

import logging
from typing import Iterable, Optional

from app.channels.gateway import ChannelGateway
from app.channels.middleware import (
    AuthenticationHook,
    GlobalLLMTokenBudgetHook,
    MetricsHook,
    MetricsPostHook,
    PIIFilterHook,
    RateLimitHook,
)
from app.channels.runtime import RAGServiceProtocol

logger = logging.getLogger(__name__)


def create_channel_gateway(
    rag_service: RAGServiceProtocol,
    register_default_hooks: bool = False,
    rate_limit_capacity: int = 20,
    rate_limit_refill_rate: float = 1.0,
    global_daily_llm_token_budget: int = 10_000_000,
    max_completion_tokens: int = 4096,
    llm_token_reservation_per_request: int = 100_000,
    valid_tokens: Optional[Iterable[str]] = None,
    ingress_context_service: Optional[object] = None,
    response_enricher: Optional[object] = None,
) -> ChannelGateway:
    """Create and configure channel gateway.

    Args:
        rag_service: RAG service for query processing.
        register_default_hooks: Whether to register default middleware hooks.
        rate_limit_capacity: Token bucket capacity for rate limiting.
        rate_limit_refill_rate: Token refill rate per second.
        global_daily_llm_token_budget: Conservative UTC-day reservation ceiling.
        max_completion_tokens: Completion-token reservation per admitted request.
        llm_token_reservation_per_request: Fixed full-workflow admission reservation.
        valid_tokens: Optional token whitelist for authenticated channels.

    Returns:
        Configured ChannelGateway instance.
    """
    gateway = ChannelGateway(
        rag_service=rag_service,
        ingress_context_service=ingress_context_service,
        response_enricher=response_enricher,
    )

    if register_default_hooks:
        # Register pre-processing hooks
        gateway.register_pre_hook(
            RateLimitHook(
                capacity=rate_limit_capacity,
                refill_rate=rate_limit_refill_rate,
            )
        )
        gateway.register_pre_hook(
            GlobalLLMTokenBudgetHook(
                daily_token_budget=global_daily_llm_token_budget,
                max_completion_tokens=max_completion_tokens,
                reservation_tokens_per_request=llm_token_reservation_per_request,
            )
        )
        token_set = set(valid_tokens) if valid_tokens is not None else None
        gateway.register_pre_hook(AuthenticationHook(valid_tokens=token_set))
        metrics_hook = MetricsHook()
        gateway.register_pre_hook(metrics_hook)

        # Register post-processing hooks
        gateway.register_post_hook(MetricsPostHook(metrics_hook))
        gateway.register_post_hook(PIIFilterHook())

        logger.info("Registered default gateway hooks")

    return gateway

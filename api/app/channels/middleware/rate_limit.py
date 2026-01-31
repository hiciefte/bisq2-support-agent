"""Rate limiting middleware hook.

Implements per-user rate limiting using token bucket algorithm.
"""

import logging
from typing import Dict, Optional

from app.channels.hooks import BasePreProcessingHook, HookPriority
from app.channels.models import GatewayError, IncomingMessage
from app.channels.security import ErrorFactory, TokenBucket

logger = logging.getLogger(__name__)


class RateLimitHook(BasePreProcessingHook):
    """Pre-processing hook for rate limiting.

    Uses token bucket algorithm to limit requests per user.

    Args:
        capacity: Maximum tokens in bucket (burst capacity).
        refill_rate: Tokens added per second.
    """

    def __init__(
        self,
        capacity: int = 20,
        refill_rate: float = 1.0,
    ):
        """Initialize rate limit hook.

        Args:
            capacity: Bucket capacity (burst limit).
            refill_rate: Tokens per second refill rate.
        """
        super().__init__(name="rate_limit", priority=HookPriority.HIGH)
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._buckets: Dict[str, TokenBucket] = {}

    def _get_bucket(self, user_id: str) -> TokenBucket:
        """Get or create token bucket for user.

        Args:
            user_id: User identifier.

        Returns:
            TokenBucket for the user.
        """
        if user_id not in self._buckets:
            self._buckets[user_id] = TokenBucket(
                capacity=self.capacity, refill_rate=self.refill_rate
            )
        return self._buckets[user_id]

    async def execute(self, message: IncomingMessage) -> Optional[GatewayError]:
        """Check rate limit for incoming message.

        Args:
            message: Incoming message to check.

        Returns:
            None if allowed, GatewayError if rate limited.
        """
        user_id = message.user.user_id
        bucket = self._get_bucket(user_id)

        allowed, metadata = bucket.consume(1)

        if allowed:
            self._logger.debug(
                f"Rate limit check passed for user {user_id}: "
                f"{metadata.get('tokens_remaining')} tokens remaining"
            )
            return None

        self._logger.warning(
            f"Rate limit exceeded for user {user_id}: "
            f"retry after {metadata.get('retry_after_seconds')}s"
        )

        return ErrorFactory.rate_limit_exceeded(
            limit=self.capacity,
            window_seconds=int(self.capacity / self.refill_rate),
            retry_after_seconds=metadata.get("retry_after_seconds", 1),
        )

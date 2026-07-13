"""Rate limiting middleware hook.

Implements per-user rate limiting using token bucket algorithm.
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Dict, Optional

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
        self._stale_bucket_ttl_seconds = (
            (self.capacity / self.refill_rate) * 2 if self.refill_rate > 0 else 3600.0
        )

    def _prune_stale_buckets(self, now: datetime) -> None:
        """Prune stale token buckets to prevent unbounded memory growth."""
        self._buckets = {
            uid: bucket
            for uid, bucket in self._buckets.items()
            if (now - bucket.last_refill).total_seconds()
            < self._stale_bucket_ttl_seconds
        }

    def _get_bucket(self, user_id: str) -> TokenBucket:
        """Get or create token bucket for user.

        Args:
            user_id: User identifier.

        Returns:
            TokenBucket for the user.
        """
        if user_id not in self._buckets:
            self._prune_stale_buckets(datetime.now(timezone.utc))
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


class GlobalLLMTokenBudgetHook(BasePreProcessingHook):
    """Fail closed when the process-wide UTC-day reservation budget is exhausted.

    Each admitted request reserves an operator-selected fixed worst-case amount
    that accounts for the complete RAG workflow, not merely user text. This is an
    admission circuit breaker rather than provider billing reconciliation. The
    deployment runs one API process; a process restart resets this in-memory
    counter, which is documented explicitly rather than presented as exact usage.
    """

    def __init__(
        self,
        daily_token_budget: int,
        max_completion_tokens: int,
        reservation_tokens_per_request: Optional[int] = None,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        super().__init__(name="global_llm_budget", priority=120)
        if daily_token_budget <= 0:
            raise ValueError("daily_token_budget must be positive")
        if max_completion_tokens <= 0:
            raise ValueError("max_completion_tokens must be positive")
        reservation = reservation_tokens_per_request or max_completion_tokens
        if reservation <= 0:
            raise ValueError("reservation_tokens_per_request must be positive")
        self.daily_token_budget = daily_token_budget
        self.max_completion_tokens = max_completion_tokens
        self.reservation_tokens_per_request = reservation
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._budget_day: Optional[date] = None
        self._reserved_tokens = 0

    def should_skip(self, message: IncomingMessage) -> bool:
        """The application-wide circuit breaker is never bypassable."""
        return False

    def _estimate_tokens(self, message: IncomingMessage) -> int:
        del message
        return self.reservation_tokens_per_request

    async def execute(self, message: IncomingMessage) -> Optional[GatewayError]:
        now = self._now().astimezone(timezone.utc)
        if self._budget_day != now.date():
            self._budget_day = now.date()
            self._reserved_tokens = 0

        reservation = self._estimate_tokens(message)
        if self._reserved_tokens + reservation <= self.daily_token_budget:
            self._reserved_tokens += reservation
            return None

        next_day = datetime.combine(
            now.date() + timedelta(days=1), time.min, tzinfo=timezone.utc
        )
        retry_after = max(1, int((next_day - now).total_seconds()))
        error = ErrorFactory.rate_limit_exceeded(
            limit=self.daily_token_budget,
            window_seconds=86400,
            retry_after_seconds=retry_after,
        )
        error.error_message = "Global daily LLM reservation budget exhausted."
        error.details.update(
            {
                "scope": "global_daily_llm_reservations",
                "reserved_tokens": self._reserved_tokens,
                "requested_reservation": reservation,
            }
        )
        self._logger.error(
            "Global daily LLM reservation budget exhausted: reserved=%s requested=%s limit=%s",
            self._reserved_tokens,
            reservation,
            self.daily_token_budget,
        )
        return error

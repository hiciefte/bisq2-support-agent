"""Metrics middleware hook.

Implements request/response metrics collection.
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Optional

from app.channels.hooks import BasePreProcessingHook, HookPriority
from app.channels.models import (ChannelType, GatewayError, IncomingMessage,
                                 OutgoingMessage)

logger = logging.getLogger(__name__)


class MetricsHook(BasePreProcessingHook):
    """Pre/Post-processing hook for metrics collection.

    Collects request and response metrics for monitoring and analysis.
    This hook is designed to never block requests.
    """

    def __init__(self):
        """Initialize metrics hook."""
        super().__init__(name="metrics", priority=HookPriority.LOW)
        self._request_count = 0
        self._response_count = 0
        self._channel_stats: Dict[ChannelType, int] = defaultdict(int)
        self._error_count = 0
        self._last_request_time: Optional[datetime] = None
        self._last_response_time: Optional[datetime] = None

    async def execute(self, message: IncomingMessage) -> Optional[GatewayError]:
        """Record incoming request metrics.

        Args:
            message: Incoming message to record.

        Returns:
            Always returns None (never blocks).
        """
        try:
            self._request_count += 1
            self._channel_stats[message.channel] += 1
            self._last_request_time = datetime.utcnow()

            self._logger.debug(
                f"Request recorded: channel={message.channel}, "
                f"total_requests={self._request_count}"
            )
        except Exception as e:
            # Never block on metrics errors
            self._logger.error(f"Failed to record request metrics: {e}")

        return None

    async def execute_post(
        self, incoming: IncomingMessage, outgoing: OutgoingMessage
    ) -> Optional[GatewayError]:
        """Record response metrics.

        Args:
            incoming: Original incoming message.
            outgoing: Response message to record.

        Returns:
            Always returns None (never blocks).
        """
        try:
            self._response_count += 1
            self._last_response_time = datetime.utcnow()

            self._logger.debug(
                f"Response recorded: channel={incoming.channel}, "
                f"total_responses={self._response_count}"
            )
        except Exception as e:
            # Never block on metrics errors
            self._logger.error(f"Failed to record response metrics: {e}")

        return None

    def get_request_count(self) -> int:
        """Get total request count.

        Returns:
            Number of requests recorded.
        """
        return self._request_count

    def get_response_count(self) -> int:
        """Get total response count.

        Returns:
            Number of responses recorded.
        """
        return self._response_count

    def get_channel_stats(self) -> Dict[ChannelType, int]:
        """Get request counts by channel.

        Returns:
            Dictionary mapping channel to request count.
        """
        return dict(self._channel_stats)

    def get_all_metrics(self) -> Dict[str, Any]:
        """Get all collected metrics.

        Returns:
            Dictionary with all metrics.
        """
        return {
            "requests": self._request_count,
            "responses": self._response_count,
            "errors": self._error_count,
            "by_channel": {
                channel.value: count for channel, count in self._channel_stats.items()
            },
            "last_request": (
                self._last_request_time.isoformat() if self._last_request_time else None
            ),
            "last_response": (
                self._last_response_time.isoformat()
                if self._last_response_time
                else None
            ),
        }

    def record_error(self) -> None:
        """Record an error occurrence."""
        self._error_count += 1

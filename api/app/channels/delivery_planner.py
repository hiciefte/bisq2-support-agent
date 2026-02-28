"""Capability-based delivery planning for channel responses."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from enum import Enum
from typing import Any


class DeliveryMode(str, Enum):
    """Delivery execution mode selected for a response."""

    SINGLE = "single"
    STREAM_NATIVE = "stream_native"
    STREAM_BUFFERED = "stream_buffered"


@dataclass(frozen=True)
class DeliveryPlan:
    """Planned delivery mode with a short reason string."""

    mode: DeliveryMode
    reason: str


class DeliveryPlanner:
    """Select delivery strategy based on response shape and channel capabilities."""

    _STREAM_ATTRS = ("stream", "answer_stream", "stream_chunks")
    _MISSING = object()

    def plan(self, *, channel: Any, response: Any) -> DeliveryPlan:
        stream = self._resolve_stream(response)
        if stream is None:
            return DeliveryPlan(mode=DeliveryMode.SINGLE, reason="no_stream_present")

        native_sender = self._resolve_native_stream_sender(channel)
        if callable(native_sender):
            return DeliveryPlan(
                mode=DeliveryMode.STREAM_NATIVE,
                reason="channel_supports_native_streaming",
            )

        return DeliveryPlan(
            mode=DeliveryMode.STREAM_BUFFERED,
            reason="stream_present_without_native_transport",
        )

    def _resolve_stream(self, response: Any) -> Any | None:
        for attr in self._STREAM_ATTRS:
            static_value = inspect.getattr_static(response, attr, self._MISSING)
            if static_value is self._MISSING:
                continue
            candidate = getattr(response, attr, None)
            if candidate is not None:
                return candidate
        return None

    @staticmethod
    def _resolve_native_stream_sender(channel: Any) -> Any | None:
        static_value = inspect.getattr_static(channel, "send_streaming_message", None)
        if static_value is None:
            return None
        return getattr(channel, "send_streaming_message", None)

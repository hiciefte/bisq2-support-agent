"""Shared channel orchestration constants."""

from __future__ import annotations

DIRECT_DELIVERY_ACTIONS = frozenset({"auto_send", "needs_clarification"})
REVIEW_QUEUE_ACTIONS = frozenset({"queue_medium", "needs_human"})

"""Shared helpers for resolving trusted support staff identities."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class StaffResolver:
    """Determine whether a sender ID belongs to trusted staff."""

    def __init__(self, trusted_staff_ids: Iterable[str]):
        self._trusted_staff_ids = {
            staff_id.strip().lower()
            for staff_id in trusted_staff_ids
            if isinstance(staff_id, str) and staff_id.strip()
        }

    def is_staff(self, sender_id: str) -> bool:
        """Return True if sender matches a trusted staff identity."""
        if not isinstance(sender_id, str):
            return False
        return sender_id.strip().lower() in self._trusted_staff_ids


def collect_trusted_staff_ids(settings: Any) -> list[str]:
    """Collect trusted staff identifiers from configured settings."""
    staff_ids: list[str] = []
    for candidate in (
        getattr(settings, "SUPPORT_AGENT_NICKNAMES", []),
        getattr(settings, "TRUSTED_STAFF_IDS", []),
    ):
        if isinstance(candidate, str):
            staff_ids.extend(
                [value.strip() for value in candidate.split(",") if value.strip()]
            )
        elif isinstance(candidate, list):
            staff_ids.extend(
                [
                    value.strip()
                    for value in candidate
                    if isinstance(value, str) and value.strip()
                ]
            )
    return sorted(set(staff_ids))

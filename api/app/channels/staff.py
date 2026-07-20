"""Shared helpers for resolving trusted support staff identities."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class StaffResolver:
    """Determine whether a sender ID belongs to trusted staff."""

    def __init__(
        self,
        trusted_staff_ids: Iterable[str],
        display_names: Iterable[str] | None = None,
        *,
        case_sensitive: bool = False,
    ):
        self._case_sensitive = case_sensitive
        self._trusted_staff_ids = {
            self._normalize_staff_id(staff_id)
            for staff_id in trusted_staff_ids
            if isinstance(staff_id, str) and staff_id.strip()
        }
        self._display_names = {
            value.strip()
            for value in (display_names or [])
            if isinstance(value, str) and value.strip()
        }

    def is_staff(self, sender_id: str) -> bool:
        """Return True if sender matches a trusted staff identity."""
        if not isinstance(sender_id, str):
            return False
        return self._normalize_staff_id(sender_id) in self._trusted_staff_ids

    def _normalize_staff_id(self, staff_id: str) -> str:
        if self._case_sensitive:
            return staff_id
        return staff_id.strip().lower()

    def get_trusted_ids(self) -> set[str]:
        """Return normalized trusted identity IDs used for authorization."""
        return set(self._trusted_staff_ids)

    def get_display_names(self) -> set[str]:
        """Return configured display names (never used for authorization)."""
        return set(self._display_names)


def staff_resolver_service_key(channel_id: str) -> str:
    """Return the runtime service key for one channel's staff identities."""
    normalized = str(channel_id or "").strip().lower()
    if not normalized:
        raise ValueError("channel_id is required for a staff resolver")
    return f"staff_resolver:{normalized}"


def resolve_channel_staff_resolver(runtime: Any, channel_id: str) -> Any | None:
    """Resolve a channel-scoped resolver with a legacy-key fallback."""
    resolve_optional = getattr(runtime, "resolve_optional", None)
    if not callable(resolve_optional):
        return None
    try:
        resolver = resolve_optional(staff_resolver_service_key(channel_id))
    except Exception:
        resolver = None
    if resolver is not None:
        return resolver
    try:
        return resolve_optional("staff_resolver")
    except Exception:
        return None


def collect_trusted_staff_ids(
    settings: Any, *, channel_id: str | None = None
) -> list[str]:
    """Collect trusted staff identifiers from configured settings."""
    staff_ids: list[str] = []
    normalized_channel_id = str(channel_id or "").strip().lower()

    if normalized_channel_id == "bisq2":
        candidates: list[Any] = [getattr(settings, "BISQ2_STAFF_PROFILE_IDS", [])]
        case_sensitive = True
    else:
        candidates = [getattr(settings, "TRUSTED_STAFF_IDS", [])]
        case_sensitive = False

    for candidate in candidates:
        if isinstance(candidate, str):
            staff_ids.extend(
                [
                    value.strip() if case_sensitive else value.strip().lower()
                    for value in candidate.split(",")
                    if value.strip()
                ]
            )
        elif isinstance(candidate, list):
            staff_ids.extend(
                [
                    value.strip() if case_sensitive else value.strip().lower()
                    for value in candidate
                    if isinstance(value, str) and value.strip()
                ]
            )
    return sorted(set(staff_ids))


def collect_staff_display_names(settings: Any) -> list[str]:
    """Collect configured display names for staff-facing UX labels only."""
    candidate = getattr(settings, "SUPPORT_AGENT_NICKNAMES", [])
    values: list[str] = []
    if isinstance(candidate, str):
        values.extend(
            [value.strip() for value in candidate.split(",") if value.strip()]
        )
    elif isinstance(candidate, list):
        values.extend(
            [
                value.strip()
                for value in candidate
                if isinstance(value, str) and value.strip()
            ]
        )
    return sorted(set(values))

"""Shared Matrix room allowlist helpers."""

from __future__ import annotations

from typing import Any, Iterable


def normalize_room_ids(room_ids: Iterable[str] | str | None) -> frozenset[str]:
    """Normalize room ids to a canonical immutable set."""
    if room_ids is None:
        return frozenset()

    if isinstance(room_ids, str):
        candidates: Iterable[str] = room_ids.split(",")
    else:
        candidates = room_ids

    normalized = {
        str(room_id or "").strip()
        for room_id in candidates
        if str(room_id or "").strip()
    }
    return frozenset(normalized)


def resolve_allowed_sync_rooms(settings: Any | None) -> frozenset[str]:
    """Read and normalize MATRIX_SYNC_ROOMS from settings-like objects."""
    if settings is None:
        return frozenset()
    return normalize_room_ids(getattr(settings, "MATRIX_SYNC_ROOMS", None))


def resolve_allowed_reaction_rooms(settings: Any | None) -> frozenset[str]:
    """Read and normalize reaction rooms from settings-like objects.

    Reaction handling must include:
    - Sync rooms (user feedback reactions)
    - Staff room (HITL approve/dismiss reactions)
    - Alert room fallback (local/dev setups)
    """
    if settings is None:
        return frozenset()

    rooms = set(resolve_allowed_sync_rooms(settings))
    staff_room = str(getattr(settings, "MATRIX_STAFF_ROOM", "") or "").strip()
    alert_room = str(getattr(settings, "MATRIX_ALERT_ROOM", "") or "").strip()
    if staff_room:
        rooms.add(staff_room)
    if alert_room:
        rooms.add(alert_room)
    return frozenset(rooms)

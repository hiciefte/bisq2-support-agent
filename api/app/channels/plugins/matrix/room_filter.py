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


def responder_room_scope(settings: Any | None) -> frozenset[str] | None:
    """Return the explicit live scope, preserving unset versus empty semantics."""
    configured = getattr(settings, "MATRIX_RESPONDER_ROOMS", None)
    return None if configured is None else normalize_room_ids(configured)


def resolve_allowed_responder_rooms(settings: Any | None) -> frozenset[str]:
    """Resolve live ingress independently from historical training imports."""
    scope = responder_room_scope(settings)
    return resolve_allowed_sync_rooms(settings) if scope is None else scope


def restrict_to_responder_rooms(
    settings: Any | None, room_ids: Iterable[str] | str | None
) -> frozenset[str]:
    """Restrict ancillary live rooms without widening the explicit scope."""
    rooms = normalize_room_ids(room_ids)
    scope = responder_room_scope(settings)
    return rooms if scope is None else rooms & scope


def is_responder_room_allowed(settings: Any | None, room_id: str) -> bool:
    """Check every live send, including staff-reviewed sends and notices."""
    scope = responder_room_scope(settings)
    return scope is None or str(room_id or "").strip() in scope


def resolve_allowed_reaction_rooms(settings: Any | None) -> frozenset[str]:
    """Read and normalize reaction rooms from settings-like objects.

    Reaction handling must include:
    - Sync rooms (user feedback reactions)
    - Staff room (HITL approve/dismiss reactions)
    - Alert room fallback (local/dev setups)
    """
    if settings is None:
        return frozenset()

    rooms = set(resolve_allowed_responder_rooms(settings))
    staff_room = str(getattr(settings, "MATRIX_STAFF_ROOM", "") or "").strip()
    alert_room = str(getattr(settings, "MATRIX_ALERT_ROOM", "") or "").strip()
    if staff_room:
        rooms.add(staff_room)
    if alert_room:
        rooms.add(alert_room)
    return restrict_to_responder_rooms(settings, rooms)

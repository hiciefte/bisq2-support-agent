"""Shared Matrix room allowlist helpers."""

from __future__ import annotations

from typing import Any, Iterable


def normalize_room_ids(room_ids: Iterable[str] | str | None) -> frozenset[str]:
    """Normalize room ids to a canonical immutable set."""
    if room_ids is None:
        return frozenset()

    if isinstance(room_ids, str):
        candidates = room_ids.split(",")
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

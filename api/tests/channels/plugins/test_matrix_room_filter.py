"""Tests for shared Matrix room allowlist helpers."""

from app.channels.plugins.matrix.room_filter import (
    normalize_room_ids,
    resolve_allowed_sync_rooms,
)


def test_normalize_room_ids_from_comma_string() -> None:
    room_ids = normalize_room_ids("!a:matrix.org, !b:matrix.org, ,")
    assert room_ids == frozenset({"!a:matrix.org", "!b:matrix.org"})


def test_normalize_room_ids_from_iterable() -> None:
    room_ids = normalize_room_ids(["!a:matrix.org", " !b:matrix.org ", ""])
    assert room_ids == frozenset({"!a:matrix.org", "!b:matrix.org"})


def test_resolve_allowed_sync_rooms_from_settings_object() -> None:
    class _Settings:
        MATRIX_SYNC_ROOMS = ["!sync:matrix.org"]

    assert resolve_allowed_sync_rooms(_Settings()) == frozenset({"!sync:matrix.org"})

"""Shared channel capability traits.

Traits are intentionally separate from channel instances so core services can
look up behavior hints without constructing plugins.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChannelTraits:
    group_room: bool = False
    supports_staff_grounding: bool = False
    supports_chatops: bool = False
    max_answer_length: int | None = None


DEFAULT_CHANNEL_TRAITS: dict[str, ChannelTraits] = {
    "web": ChannelTraits(),
    "matrix": ChannelTraits(
        group_room=True,
        supports_staff_grounding=True,
        supports_chatops=True,
        max_answer_length=500,
    ),
    "bisq2": ChannelTraits(
        group_room=True,
        supports_staff_grounding=True,
        supports_chatops=True,
        max_answer_length=500,
    ),
}


def normalize_channel_id(channel_id: str | None) -> str:
    return str(channel_id or "").strip().lower()


def get_channel_traits(channel_id: str | None) -> ChannelTraits:
    normalized = normalize_channel_id(channel_id)
    if not normalized:
        return ChannelTraits()

    from app.channels.registry import get_registered_channel_types

    channel_class = get_registered_channel_types().get(normalized)
    traits = getattr(channel_class, "CHANNEL_TRAITS", None) if channel_class else None
    if isinstance(traits, ChannelTraits):
        return traits
    return DEFAULT_CHANNEL_TRAITS.get(normalized, ChannelTraits())


def channel_is_group_room(channel_id: str | None) -> bool:
    return get_channel_traits(channel_id).group_room


def channel_supports_staff_grounding(channel_id: str | None) -> bool:
    return get_channel_traits(channel_id).supports_staff_grounding


def supported_chatops_channel_ids() -> tuple[str, ...]:
    from app.channels.registry import get_registered_channel_types

    channel_ids = set(DEFAULT_CHANNEL_TRAITS)
    channel_ids.update(get_registered_channel_types())
    return tuple(
        sorted(
            channel_id
            for channel_id in channel_ids
            if get_channel_traits(channel_id).supports_chatops
        )
    )


def declared_channel_ids() -> tuple[str, ...]:
    from app.channels.registry import get_registered_channel_types

    channel_ids = set(DEFAULT_CHANNEL_TRAITS)
    channel_ids.update(get_registered_channel_types())
    return tuple(sorted(channel_ids))

"""Fail-closed production-test scoping for the Bisq2 live channel."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

_MAX_IDENTIFIER_LENGTH = 256
_SCOPE_CONFLICT_MARKER = "_bisq2ScopeConflict"


@dataclass(frozen=True)
class Bisq2TestScope:
    """Immutable exact-match scope shared by Bisq2 ingress and egress."""

    allowed_channel_ids: frozenset[str] = field(default_factory=frozenset, repr=False)
    allowed_sender_profile_ids: frozenset[str] = field(
        default_factory=frozenset,
        repr=False,
    )
    valid: bool = True
    reason: str = "configured"

    @property
    def channel_count(self) -> int:
        """Return a safe-to-report channel count without exposing values."""
        return len(self.allowed_channel_ids)

    @property
    def sender_profile_count(self) -> int:
        """Return a safe-to-report identity count without exposing values."""
        return len(self.allowed_sender_profile_ids)

    @property
    def ready(self) -> bool:
        """A live Bisq lane requires both valid, nonempty scope dimensions."""
        return bool(
            self.valid and self.allowed_channel_ids and self.allowed_sender_profile_ids
        )

    @property
    def fingerprint(self) -> str:
        """Return a canonical one-way binding for persisted live-channel state."""
        payload = {
            "channels": sorted(self.allowed_channel_ids),
            "sender_profiles": sorted(self.allowed_sender_profile_ids),
            "version": 1,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def allows_channel(self, channel_id: Any) -> bool:
        """Authorize one exact, case-sensitive group-channel ID."""
        if not self.valid or not isinstance(channel_id, str):
            return False
        return bool(channel_id) and channel_id in self.allowed_channel_ids

    def allows_sender_profile(self, sender_profile_id: Any) -> bool:
        """Authorize one exact, case-sensitive originating profile ID."""
        if not self.valid or not isinstance(sender_profile_id, str):
            return False
        return (
            bool(sender_profile_id)
            and sender_profile_id in self.allowed_sender_profile_ids
        )

    def resolve_payload_channel(self, payload: Mapping[str, Any] | None) -> str:
        """Resolve one group channel, rejecting conflicting aliases."""
        if not isinstance(payload, Mapping) or payload.get(_SCOPE_CONFLICT_MARKER):
            return ""
        keys = (
            "channelId",
            "channel_id",
            "conversationId",
            "conversation_id",
        )
        if _has_malformed_alias(payload, *keys):
            return ""
        return _consistent_string(
            payload,
            *keys,
        )

    def resolve_payload_sender_profile(
        self,
        payload: Mapping[str, Any] | None,
    ) -> str:
        """Resolve one originating profile, rejecting conflicting aliases."""
        if not isinstance(payload, Mapping) or payload.get(_SCOPE_CONFLICT_MARKER):
            return ""
        keys = (
            "senderUserProfileId",
            "sender_user_profile_id",
            "authorId",
            "author_id",
            "senderId",
            "sender_id",
        )
        if _has_malformed_alias(payload, *keys):
            return ""
        return _consistent_string(
            payload,
            *keys,
        )

    def allows_outbound(self, channel_id: Any, sender_profile_id: Any) -> bool:
        """Authorize egress only for an approved channel and originating user."""
        return self.allows_channel(channel_id) and self.allows_sender_profile(
            sender_profile_id
        )

    def allows_payload(self, payload: Mapping[str, Any] | None) -> bool:
        """Authorize ingress only when both exact dimensions match."""
        return self.allows_outbound(
            self.resolve_payload_channel(payload),
            self.resolve_payload_sender_profile(payload),
        )


def resolve_bisq2_test_scope(settings: Any | None) -> Bisq2TestScope:
    """Build the master Bisq2 production-test scope from settings.

    Missing, malformed, wildcard, or cross-scope configuration always resolves
    to deny-all. Configured identifiers are intentionally absent from reprs,
    status payloads, and error reasons.
    """
    if settings is None:
        return _invalid_scope("missing_allowlists")

    channel_ids, channel_ids_valid = _normalize_ids(
        getattr(settings, "BISQ2_ALLOWED_CHANNEL_IDS", None)
    )
    if not channel_ids_valid:
        return _invalid_scope("invalid_channel_allowlist")

    sender_ids, sender_ids_valid = _normalize_ids(
        getattr(settings, "BISQ2_ALLOWED_SENDER_PROFILE_IDS", None)
    )
    if not sender_ids_valid:
        return _invalid_scope("invalid_sender_allowlist")

    chatops_ids, chatops_valid = _normalize_ids(
        getattr(settings, "BISQ2_CHATOPS_CHANNEL_IDS", None)
    )
    if not chatops_valid:
        return _invalid_scope("invalid_chatops_scope")
    chatops_enabled = getattr(settings, "BISQ2_CHATOPS_ENABLED", False) is True
    if chatops_enabled and not chatops_ids:
        return _invalid_scope("empty_enabled_chatops_scope")
    if not chatops_ids.issubset(channel_ids):
        return _invalid_scope("chatops_outside_channel_allowlist")

    staff_ids, staff_ids_valid = _normalize_ids(
        getattr(settings, "BISQ2_STAFF_PROFILE_IDS", None)
    )
    if not staff_ids_valid:
        return _invalid_scope("invalid_staff_profile_scope")
    if not staff_ids.issubset(sender_ids):
        return _invalid_scope("staff_profiles_outside_sender_allowlist")
    if chatops_enabled and not staff_ids:
        return _invalid_scope("empty_enabled_chatops_staff_scope")

    staff_target = getattr(settings, "BISQ2_STAFF_NOTIFICATION_TARGET", None)
    if staff_target is not None and not isinstance(staff_target, str):
        return _invalid_scope("invalid_staff_target")
    normalized_staff_target = str(staff_target or "").strip()
    if normalized_staff_target:
        if not _is_safe_identifier(normalized_staff_target):
            return _invalid_scope("invalid_staff_target")
        if normalized_staff_target not in channel_ids:
            return _invalid_scope("staff_target_outside_channel_allowlist")

    if not channel_ids:
        reason = "empty_channel_allowlist"
    elif not sender_ids:
        reason = "empty_sender_allowlist"
    else:
        reason = "configured"
    return Bisq2TestScope(
        allowed_channel_ids=channel_ids,
        allowed_sender_profile_ids=sender_ids,
        valid=True,
        reason=reason,
    )


def payloads_have_scope_conflict(
    outer: Mapping[str, Any],
    nested: Mapping[str, Any],
) -> bool:
    """Return whether nested and outer DTOs disagree on a scope identifier."""
    channel_values = _nonempty_strings(
        outer,
        "channelId",
        "channel_id",
        "conversationId",
        "conversation_id",
    ) | _nonempty_strings(
        nested,
        "channelId",
        "channel_id",
        "conversationId",
        "conversation_id",
    )
    sender_values = _nonempty_strings(
        outer,
        "senderUserProfileId",
        "sender_user_profile_id",
        "authorId",
        "author_id",
        "senderId",
        "sender_id",
    ) | _nonempty_strings(
        nested,
        "senderUserProfileId",
        "sender_user_profile_id",
        "authorId",
        "author_id",
        "senderId",
        "sender_id",
    )
    scope_keys = (
        "channelId",
        "channel_id",
        "conversationId",
        "conversation_id",
        "senderUserProfileId",
        "sender_user_profile_id",
        "authorId",
        "author_id",
        "senderId",
        "sender_id",
    )
    return bool(
        len(channel_values) > 1
        or len(sender_values) > 1
        or _has_malformed_alias(outer, *scope_keys)
        or _has_malformed_alias(nested, *scope_keys)
    )


def mark_scope_conflict(payload: dict[str, Any]) -> None:
    """Mark an internal normalized DTO as ambiguous so the scope denies it."""
    payload[_SCOPE_CONFLICT_MARKER] = True


def _normalize_ids(value: Any) -> tuple[frozenset[str], bool]:
    if value is None:
        return frozenset(), True

    candidates: Iterable[Any]
    if isinstance(value, str):
        if not value.strip():
            return frozenset(), True
        candidates = value.split(",")
    elif isinstance(value, (list, tuple, set, frozenset)):
        candidates = value
    else:
        return frozenset(), False

    normalized: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, str):
            return frozenset(), False
        item = candidate.strip()
        if not item or not _is_safe_identifier(item):
            return frozenset(), False
        normalized.add(item)
    return frozenset(normalized), True


def _is_safe_identifier(value: str) -> bool:
    if not value or len(value) > _MAX_IDENTIFIER_LENGTH:
        return False
    if value in {".", ".."}:
        return False
    if any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        return False
    return not any(character in value for character in ("*", "/", "\\", "?", "#", "%"))


def _consistent_string(payload: Mapping[str, Any], *keys: str) -> str:
    values = _nonempty_strings(payload, *keys)
    if len(values) != 1:
        return ""
    return next(iter(values))


def _has_malformed_alias(payload: Mapping[str, Any], *keys: str) -> bool:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            return True
    return False


def _nonempty_strings(payload: Mapping[str, Any], *keys: str) -> set[str]:
    values: set[str] = set()
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            values.add(value)
    return values


def _invalid_scope(reason: str) -> Bisq2TestScope:
    return Bisq2TestScope(valid=False, reason=reason)

"""Shared conversation-history construction for channel adapters.

Channel adapters can map native events/messages to ConversationMessage and reuse
this builder so context logic stays consistent across channels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass(frozen=True)
class ConversationMessage:
    """Normalized conversation message used for context assembly."""

    message_id: str
    conversation_id: str
    sender_id: str
    sender_alias: str
    text: str
    timestamp_ms: int
    citation_message_id: str | None = None
    immutable_sender_id: str | None = None


def build_channel_chat_history(
    messages: Sequence[ConversationMessage],
    *,
    current_message_id: str,
    requester_id: str,
    is_staff_message: Callable[[ConversationMessage], bool],
    max_recent_user_messages: int = 2,
    max_history_messages: int = 8,
    max_message_chars: int = 220,
) -> list[dict[str, str]] | None:
    """Build compact, thread-focused context for channel message processing.

    Strategy:
    - Keep the requester's current message plus up to N recent requester messages.
    - Include adjacent previous staff message for each requester turn.
    - Follow citations only from already-selected messages to older context.
    - Include non-requesters only when the channel marks them as trusted staff.
    """
    if not current_message_id or not requester_id:
        return None

    ordered = sorted(messages, key=lambda msg: (msg.timestamp_ms, msg.message_id))
    index_by_id = {msg.message_id: idx for idx, msg in enumerate(ordered)}
    current_index = index_by_id.get(current_message_id)
    if current_index is None:
        return None

    current = ordered[current_index]
    included_ids: set[str] = {current.message_id}

    requester_count = 0
    for idx in range(current_index, -1, -1):
        candidate = ordered[idx]
        if candidate.sender_id != requester_id:
            continue
        if not _normalize(candidate.text):
            continue
        if requester_count >= max_recent_user_messages:
            break

        included_ids.add(candidate.message_id)
        requester_count += 1
        _include_adjacent_previous_staff(
            ordered=ordered,
            requester_id=requester_id,
            requester_index=idx,
            included_ids=included_ids,
            is_staff_message=is_staff_message,
        )

    _expand_cited_context(ordered=ordered, included_ids=included_ids)

    history: list[dict[str, str]] = []
    for msg in ordered:
        if msg.message_id not in included_ids:
            continue
        normalized_text = _normalize(msg.text)
        if not normalized_text:
            continue
        if msg.sender_id == requester_id:
            role = "user"
        elif is_staff_message(msg):
            role = "assistant"
        else:
            continue
        history.append(
            {
                "role": role,
                "content": _to_history_content(normalized_text, max_message_chars),
            }
        )

    if not history:
        return None

    current_expected = _to_history_content(
        _normalize(current.text) or "", max_message_chars
    )
    if current_expected and not any(
        entry.get("role") == "user" and entry.get("content") == current_expected
        for entry in history
    ):
        history.append({"role": "user", "content": current_expected})

    if len(history) > max_history_messages:
        history = history[-max_history_messages:]
    return history or None


def _include_adjacent_previous_staff(
    *,
    ordered: Sequence[ConversationMessage],
    requester_id: str,
    requester_index: int,
    included_ids: set[str],
    is_staff_message: Callable[[ConversationMessage], bool],
) -> None:
    idx = requester_index - 1
    while idx >= 0:
        candidate = ordered[idx]
        if not _normalize(candidate.text):
            idx -= 1
            continue
        if candidate.sender_id == requester_id:
            return
        if is_staff_message(candidate):
            included_ids.add(candidate.message_id)
        return


def _expand_cited_context(
    *, ordered: Sequence[ConversationMessage], included_ids: set[str]
) -> None:
    """Follow citations out from selected messages without reverse expansion."""
    message_by_id = {message.message_id: message for message in ordered}
    index_by_id = {message.message_id: index for index, message in enumerate(ordered)}
    changed = True
    while changed:
        changed = False
        for message_id in tuple(included_ids):
            msg = message_by_id.get(message_id)
            if msg is None:
                continue
            cited = msg.citation_message_id
            if not cited or cited not in message_by_id:
                continue
            # Citations are context only when they point backward in the
            # deterministic conversation order. A forward reference must not
            # pull a later staff message into the current user's prompt.
            if index_by_id[cited] >= index_by_id[message_id]:
                continue
            if cited not in included_ids:
                included_ids.add(cited)
                changed = True


def _normalize(text: str | None) -> str | None:
    if text is None:
        return None
    normalized = text.strip()
    return normalized or None


def _to_history_content(text: str, max_chars: int) -> str:
    collapsed = text.replace("\n", " ").replace("\r", " ")
    if len(collapsed) <= max_chars:
        return collapsed
    if max_chars <= 12:
        return collapsed[:max_chars]

    # Keep both head and tail so short version hints near the end survive truncation.
    tail_budget = max(20, max_chars // 4)
    separator = " ... "
    head_budget = max_chars - tail_budget - len(separator)
    if head_budget <= 0:
        return collapsed[:max_chars]
    return f"{collapsed[:head_budget]}{separator}{collapsed[-tail_budget:]}"

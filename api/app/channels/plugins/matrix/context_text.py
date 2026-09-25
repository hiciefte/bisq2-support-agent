"""Authored Matrix text and explicit relationships for staff-context intake."""

from typing import Any


def _content(event: Any) -> dict:
    source = getattr(event, "source", None)
    content = source.get("content") if isinstance(source, dict) else None
    return content if isinstance(content, dict) else {}


def _relation(event: Any) -> dict:
    relation = _content(event).get("m.relates_to")
    return relation if isinstance(relation, dict) else {}


def is_replacement(event: Any) -> bool:
    return _relation(event).get("rel_type") == "m.replace"


def context_relationships(event: Any) -> dict[str, str]:
    relation = _relation(event)
    reply = relation.get("m.in_reply_to")
    values = {
        "reply_to_event_id": reply.get("event_id") if isinstance(reply, dict) else None
    }
    if relation.get("rel_type") == "m.thread":
        values["thread_root_event_id"] = relation.get("event_id")
    if is_replacement(event):
        values["replaces_event_id"] = relation.get("event_id")
    return {
        key: value
        for key, value in values.items()
        if isinstance(value, str) and value.strip() and len(value) <= 512
    }


def context_text(event: Any) -> str:
    """Strip only Matrix reply fallback; edits use their explicit new content."""
    content = _content(event)
    if is_replacement(event):
        new_content = content.get("m.new_content")
        if not isinstance(new_content, dict):
            return ""
        body = new_content.get("body", "")
    else:
        body = getattr(event, "body", None)
        if not isinstance(body, str):
            body = content.get("body", "")
    if not isinstance(body, str):
        return ""
    if "reply_to_event_id" in context_relationships(event):
        lines = body.split("\n")
        first = 0
        while first < len(lines) and lines[first].startswith("> "):
            first += 1
        body = "\n".join(lines[first:])
    return body.strip()

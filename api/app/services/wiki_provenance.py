"""Keep dated wiki provenance separate from unchanged article/chunk text.

Reviewed notices are packaged, exact-title wiki annotations, never FAQ policy.
Resolve them at context construction too, so an older index cannot hide a newly
reviewed discrepancy. Evidence snapshots record the notice actually supplied.
"""

from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

SOURCE_FIELDS = ("source_revision", "source_gaps", "redirect_target")


@lru_cache(maxsize=1)
def _reviewed_notices() -> dict[str, list[dict[str, Any]]]:
    data = json.loads(
        Path(__file__).with_name("wiki_source_notices.json").read_text(encoding="utf-8")
    )
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported wiki source-notice schema")
    by_title: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    for item in data["items"]:
        if item["id"] in seen or not item["body"] or not item["sources"]:
            raise ValueError("Invalid or duplicate wiki source notice")
        seen.add(item["id"])
        for title in item["source_titles"]:
            by_title.setdefault(title, []).append(item)
    return by_title


def wiki_source_provenance(metadata: dict[str, Any]) -> dict[str, Any]:
    """Return only source fields and dated annotations for this exact wiki title."""
    if metadata.get("type") != "wiki":
        return {}
    result = {key: deepcopy(metadata[key]) for key in SOURCE_FIELDS if key in metadata}
    notices = _reviewed_notices().get(metadata.get("title"), [])
    if notices:
        result["source_notices"] = deepcopy(notices)
    return result


def wiki_context_notice(metadata: dict[str, Any]) -> str:
    """Separate provenance preamble placed before a chunk, safe under truncation.

    Article revision dates do not date expanded template definitions or claim
    current correctness. Missing metadata is reported without inventing a date.
    """
    if metadata.get("type") != "wiki":
        return ""
    provenance = wiki_source_provenance(metadata)
    revision = provenance.get("source_revision") or {}
    timestamp = revision.get("timestamp")
    revision_id = revision.get("id")
    if timestamp:
        date_note = f"Article revision timestamp: {timestamp}"
        if revision_id:
            date_note += f" (revision {revision_id})"
        date_note += ". This dates the article, not all expanded templates."
    else:
        date_note = "Article revision date is unavailable in this imported source."
    lines = [
        "[Wiki source context — added metadata, not original article text]",
        date_note,
        "Historical wiki text is not proof of current software behavior or policy. "
        "The dated checks below cover only their stated claims and releases.",
    ]
    if provenance.get("redirect_target"):
        lines.append(
            "Original redirect target: "
            + str(provenance["redirect_target"])
            + "; substantive text following the redirect was retained."
        )
    gaps = provenance.get("source_gaps") or []
    unresolved = [gap for gap in gaps if gap.get("kind") != "presentation_wrapper_only"]
    wrappers = [gap for gap in gaps if gap.get("kind") == "presentation_wrapper_only"]
    if unresolved:
        labels = sorted(
            {str(gap.get("template") or gap.get("kind")) for gap in unresolved}
        )
        lines.append(
            "Unresolved source expansions: "
            + ", ".join(labels)
            + ". Explicit markers/arguments are retained; do not infer missing values."
        )
    if wrappers:
        lines.append(
            "Warning/note presentation definitions were absent; their argument prose "
            "was retained as labeled warnings/notes, not inferred template values."
        )
    for notice in provenance.get("source_notices", []):
        lines.append(
            f"Reviewed source check [{notice['id']}; checked {notice['checked_at']}]: "
            + notice["body"]
        )
        lines.append(
            "Check sources: "
            + " ; ".join(source["url"] for source in notice["sources"])
        )
    lines.append("[End added source context; original wiki chunk follows]")
    return "\n".join(lines)

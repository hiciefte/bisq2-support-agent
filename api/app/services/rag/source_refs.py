"""Shared source-reference validation helpers for RAG evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

CODE_SOURCE_REF_PREFIX = "code:"
_UNPINNED_CODE_REVISIONS = {"head", "latest", "main", "master"}
_CODE_SOURCE_REF_RE = re.compile(
    r"^code:"
    r"(?P<repo>[A-Za-z0-9_.-]+)"
    r"@(?P<commit>[A-Za-z0-9_.-]{6,64})"
    r":(?P<path>[^:\n]+)"
    r":(?P<line_start>[1-9][0-9]*)-(?P<line_end>[1-9][0-9]*)$"
)


@dataclass(frozen=True)
class CodeSourceRef:
    """Parsed precise code source reference."""

    repo: str
    commit: str
    path: str
    line_start: int
    line_end: int


def parse_code_source_ref(ref: str) -> CodeSourceRef | None:
    """Parse a precise code source ref, returning None for invalid refs."""
    match = _CODE_SOURCE_REF_RE.match(str(ref or "").strip())
    if match is None:
        return None

    commit = match.group("commit")
    if commit.lower() in _UNPINNED_CODE_REVISIONS:
        return None

    line_start = int(match.group("line_start"))
    line_end = int(match.group("line_end"))
    if line_end < line_start:
        return None

    return CodeSourceRef(
        repo=match.group("repo"),
        commit=commit,
        path=match.group("path"),
        line_start=line_start,
        line_end=line_end,
    )


def is_code_source_ref(ref: str) -> bool:
    return str(ref or "").strip().startswith(CODE_SOURCE_REF_PREFIX)


def is_precise_code_source_ref(ref: str) -> bool:
    return parse_code_source_ref(ref) is not None


def code_source_refs(refs: Iterable[str]) -> list[str]:
    return [ref for ref in refs if is_code_source_ref(ref)]


def imprecise_code_source_refs(refs: Iterable[str]) -> list[str]:
    return [
        ref for ref in code_source_refs(refs) if not is_precise_code_source_ref(ref)
    ]

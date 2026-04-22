"""Post-extraction quality gates for the FAQ training pipeline.

Pure functions — no I/O, no mocks needed, fast to test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

_MIN_TOKEN_DEFAULT = 5
_MIN_ANSWER_CHARS = 80

_GENERIC_VERBS = frozenset(
    {
        "restart",
        "check",
        "try",
        "ensure",
        "confirm",
        "verify",
        "update",
        "reinstall",
        "refresh",
        "reboot",
    }
)

_DEFAULT_DOMAIN_TERMS = frozenset(
    {
        "bisq",
        "spv",
        "mediation",
        "arbitration",
        "ctrl+o",
        "seed",
        "wallet",
        "trade",
        "offer",
        "security deposit",
        "reputation",
        "bisq easy",
        "multisig",
        "dao",
        "bsq",
        "onion",
        "tor",
        "xattr",
        "mempool",
        "btc",
        "xmr",
        "sepa",
        "zelle",
    }
)

_TOKEN_RE = re.compile(r"\S+")
_CODE_RE = re.compile(r"[`/\\]|\.app|\.sh|\-\-\w")


def _count_tokens(text: str) -> int:
    return len(_TOKEN_RE.findall(text))


def filter_short_messages(
    messages: list[dict],
    min_tokens: int = _MIN_TOKEN_DEFAULT,
    *,
    staff_authors: set[str] | None = None,
) -> list[dict]:
    """Remove user messages that are too short to produce useful FAQ pairs.

    Staff messages are always kept (short acknowledgments like "sure" are
    valid in context of a longer answer chain).
    """
    staff = staff_authors or set()
    return [
        msg
        for msg in messages
        if msg.get("author", "") in staff
        or _count_tokens(msg.get("text", "")) >= min_tokens
    ]


@dataclass(frozen=True)
class SpecificityResult:
    is_generic: bool
    reason: str | None = None


def check_answer_specificity(
    answer_text: str,
    *,
    domain_terms: Iterable[str] | None = None,
    min_chars: int = _MIN_ANSWER_CHARS,
) -> SpecificityResult:
    """Flag answers that are too generic to be useful as FAQ entries.

    A composite of:
    - Character length (< min_chars and no code/commands → generic)
    - Presence of domain-specific nouns (Bisq, SPV, mediation, etc.)
    - Absence of ONLY generic verbs with no specifics
    """
    if not answer_text or not answer_text.strip():
        return SpecificityResult(is_generic=True, reason="empty")

    text = answer_text.strip()
    lower = text.lower()
    terms = set(domain_terms) if domain_terms else _DEFAULT_DOMAIN_TERMS

    has_domain_term = any(term in lower for term in terms)
    has_code = bool(_CODE_RE.search(text))

    if has_code:
        return SpecificityResult(is_generic=False)

    if len(text) < min_chars and not has_domain_term:
        return SpecificityResult(is_generic=True, reason="too_short_no_domain_terms")

    if not has_domain_term:
        words = set(lower.split())
        verb_overlap = words & _GENERIC_VERBS
        if verb_overlap and not has_code:
            return SpecificityResult(is_generic=True, reason="generic_verbs_only")

    return SpecificityResult(is_generic=False)


_PRE_EXTRACTION_DUPLICATE_THRESHOLD = 0.92


def is_pre_extraction_duplicate(
    max_similarity: float,
    threshold: float = _PRE_EXTRACTION_DUPLICATE_THRESHOLD,
) -> bool:
    """Check if a candidate question is too similar to an existing FAQ.

    Uses a stricter threshold (0.92) than the approval-time duplicate
    check (0.85) because pre-extraction comparison operates on the raw
    question text, which may diverge from the polished FAQ form.
    """
    return max_similarity > threshold

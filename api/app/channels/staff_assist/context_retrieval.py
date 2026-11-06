"""Bound retrieval to the focal request and confirmed requester context.

Membership is supplied by the source selector, never inferred from proximity or
the ``user`` role here. These messages must share the generation snapshot's
source-version checks; optional neighboring messages are not eligible.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.channels.security import PIIDetector
from app.channels.staff_assist.context_incidents import (
    context_only,
    helper_turn,
    new_issue,
)
from app.channels.staff_assist.public_context import RoomMessage
from app.core.pii_utils import PII_LOGGING_PATTERNS
from app.services.rag.code_evidence import (
    _SECRET_TOKEN_RE,
    explicit_product,
    explicit_user_version,
)

MAX_RETRIEVAL_QUERY_CHARS = 4000
MAX_RETRIEVAL_CONTEXT_MESSAGES = 10
_CONTEXT_HEADER = "\n\nConfirmed requester context:\n"
_QUOTED_VALUE = r'"[^"]*(?:"|$)' r"|'[^']*(?:'|$)" r"|`[^`]*(?:`|$)"
_MATRIX_TOKEN_RE = re.compile(PII_LOGGING_PATTERNS["matrix_token"])
_ASSIGNMENT = r"\b[\"']?\s*[:=]\s*"
_CREDENTIAL_LABEL = (
    r"\b(?:password|passwd|pwd|secret|(?:access[ _-]?)?token|"
    r"api[ _-]?key|private[ _-]?key|mnemonic|seed[ _-]?phrase|wallet[ _-]?seed)"
)
# Unquoted values can contain spaces and punctuation within a word. Stop at a
# sentence/field boundary, not the first word of a multiword credential.
_UNQUOTED_VALUE = r"(?:(?!;|[.!?](?:\s|$)|\n---\n)[\s\S])+"
_CREDENTIAL_VALUE_RE = re.compile(
    rf"(?P<label>{_CREDENTIAL_LABEL}{_ASSIGNMENT})"
    rf"(?P<value>{_QUOTED_VALUE}|{_UNQUOTED_VALUE})",
    re.IGNORECASE,
)
_NATURAL_CREDENTIAL_RE = re.compile(
    rf"(?P<label>{_CREDENTIAL_LABEL}\s+is\s+)"
    rf"(?P<value>{_QUOTED_VALUE}|{_UNQUOTED_VALUE})",
    re.IGNORECASE,
)
_DIAGNOSTIC_STATE = (
    r"(?:incorrect|wrong|invalid|missing|lost|rejected|expired|unavailable|"
    r"not (?:accepted|working|recognized|valid|available))"
    r"(?:\s+(?:only\s+)?(?:when|after|before|on|in|by|for|during|since|until|"
    r"with|without)\b[\s\S]*)?"
)
_DIAGNOSTIC_STATE_RE = re.compile(_DIAGNOSTIC_STATE, re.IGNORECASE)
_DIAGNOSTIC_QUERY_PREFIX_RE = re.compile(
    r"\b(?:why|when|how)\s+(?:is|was)\s+(?:my|the|this)\s*$", re.IGNORECASE
)
_DIAGNOSTIC_QUERY_SUFFIX_RE = re.compile(
    rf"(?P<secret>.+?)(?P<diagnostic>\s+{_DIAGNOSTIC_STATE})$",
    re.IGNORECASE,
)


def _sanitize(text: str, *, replacement: str = "[REDACTED]") -> str:
    """Withhold identifiers and complete credential values before retrieval."""
    text = PIIDetector().redact(text, replacement=replacement)
    for pattern in (_SECRET_TOKEN_RE, _MATRIX_TOKEN_RE):
        text = pattern.sub(replacement, text)

    def redact_value(match: re.Match[str]) -> str:
        """Keep safe diagnostic predicates while removing disclosed values."""
        value = match.group("value")
        if match.re is _NATURAL_CREDENTIAL_RE and _DIAGNOSTIC_STATE_RE.fullmatch(
            value.strip()
        ):
            return match.group(0)
        suffix = ""
        # In "Why is my token=... rejected?", the final predicate describes
        # the failure. Preserve it only in that explicit question construction.
        if _DIAGNOSTIC_QUERY_PREFIX_RE.search(match.string[: match.start()]):
            diagnostic = _DIAGNOSTIC_QUERY_SUFFIX_RE.fullmatch(value)
            if diagnostic:
                suffix = diagnostic.group("diagnostic")
        return f"{match.group('label')}{replacement}{suffix}"

    # Topic words such as "token" or "seed phrase" belong in support queries.
    # Natural disclosures and assignments redact whole values; a narrowly
    # recognized diagnostic predicate such as "is incorrect" remains useful.
    for pattern in (_NATURAL_CREDENTIAL_RE, _CREDENTIAL_VALUE_RE):
        text = pattern.sub(redact_value, text)
    return text.replace("@", "＠").strip()


def _same_scope(question: str, content: str) -> bool:
    """Do not turn conflicting or uncertain product/release wording into scope."""
    for extract in (explicit_product, explicit_user_version):
        question_scope = extract(question)
        content_scope = extract(content)
        if (question_scope or content_scope) and extract(question + "\n" + content) != (
            question_scope or content_scope
        ):
            return False
    return True


def build_retrieval_query(
    question: str, confirmed_messages: Sequence[RoomMessage] = ()
) -> str:
    """Preserve the complete focal request and append bounded attributed text.

    Callers must provide only positively confirmed, current incident/native or
    unique-relation messages, not the entire generation discussion. Speaker
    checks here are an additional ownership guard, not membership evidence.
    Complete messages retain negation, uncertainty and conditions. If a message
    does not fit, omit it instead of cutting off its qualifiers. The existing
    request contract bounds the focal question itself at 4000 characters.
    """
    if len(question) > MAX_RETRIEVAL_QUERY_CHARS:
        raise ValueError("The complete focal query must fit the request bound")
    focal = _sanitize(question)
    if len(focal) > MAX_RETRIEVAL_QUERY_CHARS:
        # A short secret can expand to [REDACTED]. A one-character marker keeps
        # every nonsecret focal condition within the existing request bound.
        focal = _sanitize(question, replacement="*")
    if not focal or len(focal) > MAX_RETRIEVAL_QUERY_CHARS:
        raise ValueError("The complete focal query must fit the request bound")

    # freeze() joins requester turns with this delimiter. Deduplicate exact
    # complete turns, not substrings that might omit negation or conditions.
    seen = {" ".join(part.split()) for part in focal.split("\n---\n")}
    seen.add(" ".join(focal.split()))
    candidates: list[str] = []
    for message in confirmed_messages:
        if message.role != "user" or message.speaker != "requester":
            continue
        content = _sanitize(message.content)
        normalized = " ".join(content.split())
        if (
            not content
            or normalized in seen
            or context_only(content)
            or helper_turn(content)
            or new_issue(content)
            or not _same_scope(focal, content)
        ):
            continue
        seen.add(normalized)
        candidates.append(content)

    # When the focal request has no unique scope, do not arbitrarily choose
    # between conflicting confirmed turns based on their ordering or length.
    for extract in (explicit_product, explicit_user_version):
        if (
            extract(focal) is None
            and len(
                {scope for text in candidates if (scope := extract(text)) is not None}
            )
            > 1
        ):
            return focal

    query = focal
    appended = 0
    for content in candidates:
        if appended >= MAX_RETRIEVAL_CONTEXT_MESSAGES:
            break
        addition = (_CONTEXT_HEADER if not appended else "\n---\n") + content
        if len(query) + len(addition) > MAX_RETRIEVAL_QUERY_CHARS:
            continue
        query += addition
        appended += 1
    return query

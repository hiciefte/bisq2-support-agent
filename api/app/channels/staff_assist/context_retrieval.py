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
_SEED_VALUE_RE = re.compile(
    r"(?P<label>\b(?:mnemonic|seed[ _-]?phrase|wallet[ _-]?seed)"
    + _ASSIGNMENT
    + rf")(?P<value>{_QUOTED_VALUE}|[^;.!?]+)",
    re.IGNORECASE,
)
_CREDENTIAL_VALUE_RE = re.compile(
    r"(?P<label>\b(?:password|passwd|pwd|secret|(?:access[ _-]?)?token|"
    r"api[ _-]?key|private[ _-]?key)"
    + _ASSIGNMENT
    + rf")(?P<value>{_QUOTED_VALUE}|[^\s,;]+)",
    re.IGNORECASE,
)


def _sanitize(text: str) -> str:
    text = PIIDetector().redact(text)
    for pattern in (_SECRET_TOKEN_RE, _MATRIX_TOKEN_RE):
        text = pattern.sub("[REDACTED]", text)
    # Topic words such as "token" or "seed phrase" belong in support queries.
    # Redact an actual assigned value without removing the subject of a request.
    # Natural "is" clauses can contain diagnostic negation, not a secret value.
    # Seed payloads may contain multiple words. Keep the entire value out of
    # retrieval; a token-only assignment matcher would leak the remaining words.
    for pattern in (_SEED_VALUE_RE, _CREDENTIAL_VALUE_RE):
        text = pattern.sub(lambda match: f"{match.group('label')}[REDACTED]", text)
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
    focal = _sanitize(question)
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

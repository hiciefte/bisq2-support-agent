#!/usr/bin/env python3
"""Extract reviewable Matrix Q/A benchmark and staff-behavior samples.

This script reads a Matrix room export JSON and extracts staff-reply Q/A pairs.
It emits:
1) samples JSON usable by run_ragas_evaluation.py
2) review JSON with selection details and rejection reasons
3) a sanitized behavior-review artifact that also retains diagnostic/link-only replies
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Keep import behavior aligned with other scripts in this repo.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.core.pii_utils import redact_for_logs  # noqa: E402
from app.services.rag.protocol_detector import ProtocolDetector  # noqa: E402

DEFAULT_INPUT = "api/data/sample_matrix_messages.json"
DEFAULT_OUTPUT = "api/data/evaluation/matrix_realistic_qa_samples.json"
DEFAULT_REVIEW = "api/data/evaluation/matrix_realistic_qa_review.json"
DEFAULT_BEHAVIOR_OUTPUT = "api/data/evaluation/matrix_staff_behavior_review.json"
BEHAVIOR_SCHEMA_VERSION = 1
DEFAULT_MISSING_MATCH_THRESHOLD = 0.75

QUESTION_MIN_CHARS = 20
QUESTION_MIN_WORDS = 5
ANSWER_MIN_CHARS = 35
ANSWER_MIN_WORDS = 8

CLARIFYING_ANSWER_PATTERNS = [
    r"^can you explain",
    r"^what do you mean",
    r"^could you clarify",
    r"^what exactly",
    r"^which .* are you",
    r"^are you on .*\?$",
    r"^what('?s| is) the (exact )?error",
    r"^please (give|provide|share|send)",
    r"^did you .*",
    r"^have you tried",
]

QUESTION_INDICATORS = [
    r"\?$",
    r"\bhow\b",
    r"\bwhat\b",
    r"\bwhy\b",
    r"\bwhen\b",
    r"\bwhere\b",
    r"\bcan i\b",
    r"\bcould i\b",
    r"\bshould i\b",
    r"\bis it\b",
    r"\bdo i\b",
    r"\bdoes\b",
    r"\bproblem\b",
    r"\berror\b",
    r"\bstuck\b",
    r"\bfailed\b",
    r"\bnot working\b",
    r"\bhelp\b",
    r"\bissue\b",
]

CONTEXT_DEPENDENT_QUESTION_PATTERNS = [
    r"^(yes|no|ok|okay|thanks|thank you|thx)\b",
    r"^(also|and|but)\b",
    r"^yes\.\s*i said",
    r"^as i said",
    r"^that\b",
    r"^this\b",
    r"^it\b",
]

REMEDY_PATTERNS = (
    (
        "delete_outdated_tor_files",
        "delete outdated tor files",
        r"\bdelete\b.{0,30}\boutdated\b.{0,20}\btor files?\b",
    ),
    (
        "spv_resync",
        "SPV resync",
        r"\bspv[ -]?resync\b|\bresync(?:ing)?\b.{0,20}\bspv\b",
    ),
    (
        "copy_data_directory_as_is",
        "copy the data directory as-is",
        r"\bcopy\b.{0,30}\bdata director(?:y|ies)\b.{0,20}\bas[ -]?is\b",
    ),
    (
        "revert_to_normal_sepa",
        "revert to normal SEPA",
        r"\b(?:revert|switch)\b.{0,25}\bnormal sepa\b",
    ),
    (
        "open_mediation_ctrl_o",
        "Ctrl-O",
        r"\b(?:ctrl|cmd)[-+ ]o\b.{0,40}\bmediation\b|\bmediation\b.{0,40}\b(?:ctrl|cmd)[-+ ]o\b",
    ),
)
REMEDY_TERMS = {tag: term for tag, term, _pattern in REMEDY_PATTERNS}
SCAM_QUESTION_RE = re.compile(
    r"\b(?:scam(?:mer)?|phish(?:ing)?|spoof(?:ed|ing)?|seed words?|seed phrase|"
    r"private keys?|direct message|private message|\bdm\b)\b",
    re.IGNORECASE,
)
TROUBLESHOOTING_RE = re.compile(
    r"\b(?:stuck|error|failed|failure|not working|won't|cannot|can't|sync|resync|"
    r"payment|trade issue|problem|restart)\b",
    re.IGNORECASE,
)
URL_CANDIDATE_RE = re.compile(r"https?://[^\s<>()\[\]{}]+", re.IGNORECASE)
ONION_URL_RE = re.compile(
    r"https?://[a-z2-7]{16,56}\.onion[^\s<>()\[\]{}]*", re.IGNORECASE
)
URL_SECRET_RE = re.compile(
    r"(?i)([?&](?:access_?token|auth|key|password|secret|session|token)=)[^&\s]+"
)
MATRIX_IDENTIFIER_RE = re.compile(
    r"(?<!\w)(?:"
    r"[@!#][^\s:]{1,255}:[a-z0-9.-]+(?::\d+)?"
    r"|\$[a-z0-9_+/=-]{16,}(?::[a-z0-9.-]+(?::\d+)?)?"
    r")",
    re.IGNORECASE,
)
MATCH_TOKEN_RE = re.compile(r"[a-z0-9]+")
MATCH_STOPWORDS = {
    "a",
    "an",
    "and",
    "after",
    "are",
    "before",
    "bisq",
    "can",
    "could",
    "did",
    "do",
    "does",
    "during",
    "failed",
    "failure",
    "for",
    "help",
    "how",
    "i",
    "in",
    "is",
    "issue",
    "it",
    "my",
    "of",
    "on",
    "problem",
    "remains",
    "restart",
    "should",
    "still",
    "stuck",
    "the",
    "to",
    "what",
    "when",
    "why",
    "with",
    "you",
    "your",
}
FORBIDDEN_MISSING_FAQ_KEYS = {"sender", "event_id", "room_id", "user_id"}
ALLOWED_MISSING_FAQ_KEYS = {"reference", "question", "created_at_ms"}


@dataclass
class CandidatePair:
    question: str
    answer: str
    protocol: str
    protocol_confidence: float
    question_sender: str
    answer_sender: str
    question_event_id: str
    answer_event_id: str
    question_ts: int
    answer_ts: int
    score: float
    is_diagnostic_reply: bool
    is_link_only_reply: bool
    wiki_links: tuple[str, ...]
    remedy_tags: tuple[str, ...]


@dataclass(frozen=True)
class MissingFAQQuestion:
    reference_hash: str
    question: str
    created_at_ms: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_sender_identity(sender_id: str, *, salt: str) -> str:
    normalized = (sender_id or "").strip().lower()
    payload = f"{salt}\x1fmatrix-sender\x1f{normalized}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _hash_reference(value: str, *, namespace: str, salt: str) -> str:
    normalized = (value or "").strip()
    payload = f"{salt}\x1f{namespace}\x1f{normalized}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _redact_known_identifiers(text: str, identifiers: set[str]) -> str:
    redacted = text
    for identifier in sorted(identifiers, key=lambda value: (-len(value), value)):
        if identifier:
            redacted = redacted.replace(identifier, "[matrix-identifier]")
    return MATRIX_IDENTIFIER_RE.sub("[matrix-identifier]", redacted)


def _localpart(matrix_id: str) -> str:
    matrix_id = (matrix_id or "").strip()
    if matrix_id.startswith("@") and ":" in matrix_id:
        return matrix_id[1:].split(":", 1)[0].lower()
    return matrix_id.lower()


def _extract_body(msg: dict[str, Any]) -> str:
    content = msg.get("content")
    if not isinstance(content, dict):
        return ""
    body = content.get("body", "")
    return body if isinstance(body, str) else ""


def _reply_to_event_id(msg: dict[str, Any]) -> str | None:
    content = msg.get("content")
    if not isinstance(content, dict):
        return None
    relates = content.get("m.relates_to")
    if not isinstance(relates, dict):
        return None
    reply = relates.get("m.in_reply_to")
    if not isinstance(reply, dict):
        return None
    event_id = reply.get("event_id")
    return event_id if isinstance(event_id, str) and event_id else None


def _is_m_text_message(msg: dict[str, Any]) -> bool:
    if msg.get("type") != "m.room.message":
        return False
    content = msg.get("content")
    if not isinstance(content, dict):
        return False
    msgtype = content.get("msgtype")
    return msgtype in (None, "m.text")


def _clean_reply_body(text: str) -> str:
    lines = text.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if line.startswith(">") or line == "":
            idx += 1
            continue
        break
    cleaned = "\n".join(lines[idx:]).strip()
    return _norm_space(cleaned or text)


def _looks_like_link_only(text: str) -> bool:
    return bool(re.fullmatch(r"https?://\S+", text.strip()))


def _looks_like_clarifying_answer(text: str) -> bool:
    text = text.strip()
    if text.endswith("?") and len(text.split()) <= 14:
        return True
    for pattern in CLARIFYING_ANSWER_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _is_valid_bisq_wiki_url(value: str) -> bool:
    """Return whether a URL is an exact, credential-free Bisq wiki URL."""
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme.lower() == "https"
            and parsed.hostname == "bisq.wiki"
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
        )
    except (TypeError, ValueError):
        return False


def _extract_wiki_links(text: str) -> tuple[str, ...]:
    links = {
        candidate
        for match in URL_CANDIDATE_RE.findall(text)
        if (candidate := match.rstrip(".,;:!?\"'"))
        and _is_valid_bisq_wiki_url(candidate)
    }
    return tuple(sorted(links, key=lambda value: (value.lower(), value)))


def _sanitize_review_text(text: str, identifiers: set[str]) -> str:
    """Redact identifiers and PII while preserving validated public wiki links."""
    sanitized = _redact_known_identifiers(text, identifiers)
    preserved_links: dict[str, str] = {}
    for index, link in enumerate(_extract_wiki_links(sanitized)):
        if (
            redact_for_logs(link) != link
            or URL_SECRET_RE.search(link)
            or MATRIX_IDENTIFIER_RE.search(link)
            or ".onion" in link.lower()
        ):
            sanitized = sanitized.replace(link, "[REDACTED_WIKI_URL]")
            continue
        placeholder = f"[BISQ_WIKI_LINK_{index}]"
        preserved_links[placeholder] = link
        sanitized = sanitized.replace(link, placeholder)

    sanitized = redact_for_logs(sanitized)
    sanitized = ONION_URL_RE.sub("[ONION_URL]", sanitized)
    sanitized = URL_SECRET_RE.sub(r"\1[REDACTED]", sanitized)
    for placeholder, link in preserved_links.items():
        sanitized = sanitized.replace(placeholder, link)
    return sanitized


def _extract_remedy_tags(text: str) -> tuple[str, ...]:
    return tuple(
        tag
        for tag, _term, pattern in REMEDY_PATTERNS
        if re.search(pattern, text, re.IGNORECASE)
    )


def _normalize_match_text(text: str) -> str:
    return " ".join(MATCH_TOKEN_RE.findall(text.lower()))


def _match_tokens(text: str) -> set[str]:
    return {
        token
        for token in MATCH_TOKEN_RE.findall(text.lower())
        if token not in MATCH_STOPWORDS
    }


def _question_match_score(left: str, right: str) -> tuple[float, str]:
    left_normalized = _normalize_match_text(left)
    right_normalized = _normalize_match_text(right)
    if left_normalized == right_normalized:
        return 1.0, "exact_normalized_question"

    left_tokens = _match_tokens(left)
    right_tokens = _match_tokens(right)
    shared = left_tokens & right_tokens
    if len(shared) < 2 or not left_tokens or not right_tokens:
        return 0.0, "insufficient_lexical_overlap"

    containment = len(shared) / min(len(left_tokens), len(right_tokens))
    union = left_tokens | right_tokens
    jaccard = len(shared) / len(union)
    sequence = SequenceMatcher(None, left_normalized, right_normalized).ratio()

    if len(shared) >= 3 and containment >= 0.8:
        score = max(0.85, 0.55 * containment + 0.25 * jaccard + 0.20 * sequence)
        return min(score, 0.99), "strong_token_containment"

    score = 0.45 * containment + 0.30 * jaccard + 0.25 * sequence
    return min(score, 0.99), "combined_lexical_similarity"


def _load_missing_faq_questions(
    path: Path, *, sender_hash_salt: str
) -> list[MissingFAQQuestion]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        rows = data.get("missing_faq_questions")
    elif isinstance(data, list):
        rows = data
    else:
        raise ValueError("missing-FAQ input must be a list or an object with a list")

    if not isinstance(rows, list):
        raise ValueError("missing-FAQ input does not contain missing_faq_questions")

    questions: list[MissingFAQQuestion] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"missing-FAQ row {index} must be an object")

        keys = set(row)
        forbidden = keys & FORBIDDEN_MISSING_FAQ_KEYS
        if forbidden:
            names = ", ".join(sorted(forbidden))
            raise ValueError(
                f"missing-FAQ row {index} contains forbidden keys: {names}"
            )
        unexpected = keys - ALLOWED_MISSING_FAQ_KEYS
        if unexpected:
            names = ", ".join(sorted(unexpected))
            raise ValueError(
                f"missing-FAQ row {index} contains unexpected keys: {names}"
            )

        reference = row.get("reference")
        question = row.get("question")
        created_at_ms = row.get("created_at_ms")
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError(f"missing-FAQ row {index} requires a reference")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"missing-FAQ row {index} requires a question")
        if MATRIX_IDENTIFIER_RE.search(reference) or MATRIX_IDENTIFIER_RE.search(
            question
        ):
            raise ValueError(
                f"missing-FAQ row {index} must not contain Matrix identifiers"
            )
        if (
            not isinstance(created_at_ms, int)
            or isinstance(created_at_ms, bool)
            or created_at_ms < 0
        ):
            raise ValueError(
                f"missing-FAQ row {index} requires a non-negative created_at_ms"
            )

        questions.append(
            MissingFAQQuestion(
                reference_hash=_hash_reference(
                    reference,
                    namespace="missing-faq-reference",
                    salt=sender_hash_salt,
                ),
                question=_norm_space(question),
                created_at_ms=created_at_ms,
            )
        )

    return questions


def _find_missing_faq_match(
    candidate: CandidatePair,
    missing_questions: list[MissingFAQQuestion],
    *,
    threshold: float,
) -> dict[str, Any] | None:
    scored: list[tuple[float, str, str]] = []
    for missing in missing_questions:
        if candidate.answer_ts <= missing.created_at_ms:
            continue
        score, reason = _question_match_score(candidate.question, missing.question)
        if score > 0 and score >= threshold:
            scored.append((score, missing.reference_hash, reason))

    if not scored:
        return None

    score, reference_hash, reason = sorted(
        scored, key=lambda item: (-item[0], item[1], item[2])
    )[0]
    return {
        "reference_hash": reference_hash,
        "score": round(score, 6),
        "reason": reason,
    }


def _is_context_dependent_question(text: str) -> bool:
    lowered = text.strip().lower()
    for pattern in CONTEXT_DEPENDENT_QUESTION_PATTERNS:
        if re.search(pattern, lowered, re.IGNORECASE):
            return True
    return False


def _is_likely_standalone_question(text: str) -> bool:
    lowered = text.strip().lower()
    if _is_context_dependent_question(lowered):
        return False
    for pattern in QUESTION_INDICATORS:
        if re.search(pattern, lowered, re.IGNORECASE):
            return True
    return False


def _quality_score(
    question: str, answer: str, protocol: str, protocol_confidence: float
) -> float:
    q_words = len(question.split())
    a_words = len(answer.split())
    score = float(a_words) + min(q_words, 40) * 0.4 + protocol_confidence * 8.0
    if protocol == "multisig_v1":
        score += 1.0
    return score


def _build_staff_sets(args: argparse.Namespace) -> tuple[set[str], set[str]]:
    settings = get_settings()

    full_ids: set[str] = set()

    trusted = getattr(settings, "TRUSTED_STAFF_IDS", []) or []
    if isinstance(trusted, str):
        trusted = [s.strip() for s in trusted.split(",") if s.strip()]
    for matrix_id in trusted:
        full_ids.add(matrix_id)

    if args.staff_ids:
        full_ids.update([x.strip() for x in args.staff_ids.split(",") if x.strip()])
    localparts = {
        x.strip().lower() for x in args.staff_localparts.split(",") if x.strip()
    }

    return full_ids, localparts


def _is_staff(sender: str, staff_ids: set[str], staff_localparts: set[str]) -> bool:
    if sender in staff_ids:
        return True
    return _localpart(sender) in staff_localparts


def extract_candidates(
    messages: list[dict[str, Any]],
    *,
    staff_ids: set[str],
    staff_localparts: set[str],
    detector: ProtocolDetector,
) -> tuple[
    list[CandidatePair],
    list[CandidatePair],
    Counter[str],
    list[dict[str, Any]],
]:
    by_event_id = {
        str(m.get("event_id")): m
        for m in messages
        if isinstance(m, dict) and m.get("event_id")
    }
    raw_identifiers = {
        str(message.get(field))
        for message in messages
        if isinstance(message, dict)
        for field in ("sender", "event_id", "room_id")
        if isinstance(message.get(field), str)
        and str(message.get(field)).startswith(("@", "$", "!", "#"))
    }

    messages_sorted = sorted(
        messages, key=lambda m: int(m.get("origin_server_ts") or 0)
    )

    candidates: list[CandidatePair] = []
    behavior_candidates: list[CandidatePair] = []
    rejects: Counter[str] = Counter()
    rejected_examples: list[dict[str, Any]] = []

    for msg in messages_sorted:
        if not isinstance(msg, dict):
            rejects["not_object"] += 1
            continue
        if not _is_m_text_message(msg):
            rejects["not_text_message"] += 1
            continue

        answer_sender = str(msg.get("sender", ""))
        if not _is_staff(answer_sender, staff_ids, staff_localparts):
            rejects["answer_not_staff"] += 1
            continue

        reply_to = _reply_to_event_id(msg)
        if not reply_to:
            rejects["staff_not_reply"] += 1
            continue

        question_msg = by_event_id.get(reply_to)
        if not isinstance(question_msg, dict):
            rejects["reply_target_missing"] += 1
            continue
        if not _is_m_text_message(question_msg):
            rejects["reply_target_not_text"] += 1
            continue

        question_sender = str(question_msg.get("sender", ""))
        if _is_staff(question_sender, staff_ids, staff_localparts):
            rejects["staff_to_staff"] += 1
            continue

        question_raw = _extract_body(question_msg)
        answer_raw = _extract_body(msg)
        question = _sanitize_review_text(_norm_space(question_raw), raw_identifiers)
        answer = _sanitize_review_text(_clean_reply_body(answer_raw), raw_identifiers)

        if (
            len(question) < QUESTION_MIN_CHARS
            or len(question.split()) < QUESTION_MIN_WORDS
        ):
            rejects["question_too_short"] += 1
            continue
        if not _is_likely_standalone_question(question):
            rejects["question_not_standalone"] += 1
            continue

        protocol_detected, confidence = detector.detect_protocol_from_text(
            f"{question}\n\n{answer}"
        )
        protocol = protocol_detected or "unknown"
        score = _quality_score(question, answer, protocol, confidence)
        candidate = CandidatePair(
            question=question,
            answer=answer,
            protocol=protocol,
            protocol_confidence=float(confidence),
            question_sender=question_sender,
            answer_sender=answer_sender,
            question_event_id=str(question_msg.get("event_id", "")),
            answer_event_id=str(msg.get("event_id", "")),
            question_ts=int(question_msg.get("origin_server_ts") or 0),
            answer_ts=int(msg.get("origin_server_ts") or 0),
            score=score,
            is_diagnostic_reply=_looks_like_clarifying_answer(answer),
            is_link_only_reply=_looks_like_link_only(answer),
            wiki_links=_extract_wiki_links(answer),
            remedy_tags=_extract_remedy_tags(answer),
        )
        if answer:
            behavior_candidates.append(candidate)

        # Preserve the legacy benchmark's answer-quality filters. The behavior
        # artifact above intentionally retains diagnostic and link-only replies.
        if len(answer) < ANSWER_MIN_CHARS or len(answer.split()) < ANSWER_MIN_WORDS:
            rejects["answer_too_short"] += 1
            continue
        if candidate.is_link_only_reply:
            rejects["answer_link_only"] += 1
            continue
        if candidate.is_diagnostic_reply:
            rejects["answer_clarifying"] += 1
            continue

        candidates.append(candidate)

    # Deduplicate by normalized question; keep highest score.
    dedup_map: dict[str, CandidatePair] = {}
    for c in candidates:
        key = _norm_space(c.question.lower())
        existing = dedup_map.get(key)
        if existing is None or c.score > existing.score:
            dedup_map[key] = c

    deduped = list(dedup_map.values())

    # Keep useful rejected examples for inspection.
    for c in sorted(deduped, key=lambda x: x.score, reverse=True)[:100]:
        if c.protocol == "unknown":
            rejected_examples.append(
                {
                    "reason": "protocol_unknown",
                    "question": c.question,
                    "answer": c.answer,
                    "question_event_id": c.question_event_id,
                    "answer_event_id": c.answer_event_id,
                    "question_sender": c.question_sender,
                    "answer_sender": c.answer_sender,
                }
            )

    return deduped, behavior_candidates, rejects, rejected_examples


def select_samples(
    candidates: list[CandidatePair],
    *,
    max_samples: int,
    bisq1_ratio: float,
    include_unknown: bool,
) -> tuple[list[CandidatePair], dict[str, int]]:
    bisq1 = sorted(
        [c for c in candidates if c.protocol == "multisig_v1"],
        key=lambda c: c.score,
        reverse=True,
    )
    bisq2 = sorted(
        [c for c in candidates if c.protocol == "bisq_easy"],
        key=lambda c: c.score,
        reverse=True,
    )
    unknown = sorted(
        [c for c in candidates if c.protocol not in {"multisig_v1", "bisq_easy"}],
        key=lambda c: c.score,
        reverse=True,
    )

    target_bisq1 = min(len(bisq1), round(max_samples * bisq1_ratio))
    selected: list[CandidatePair] = []
    selected.extend(bisq1[:target_bisq1])

    remaining = max_samples - len(selected)
    selected.extend(bisq2[:remaining])
    remaining = max_samples - len(selected)

    if remaining > 0:
        bisq1_left = bisq1[target_bisq1:]
        selected.extend(bisq1_left[:remaining])
        remaining = max_samples - len(selected)

    if remaining > 0 and include_unknown:
        selected.extend(unknown[:remaining])

    selected = sorted(selected, key=lambda c: c.answer_ts, reverse=True)
    counts = {
        "multisig_v1": sum(1 for c in selected if c.protocol == "multisig_v1"),
        "bisq_easy": sum(1 for c in selected if c.protocol == "bisq_easy"),
        "unknown": sum(
            1 for c in selected if c.protocol not in {"multisig_v1", "bisq_easy"}
        ),
    }
    return selected[:max_samples], counts


def _event_reference_hash(event_id: str, *, sender_hash_salt: str) -> str:
    return _hash_reference(
        event_id,
        namespace="matrix-event",
        salt=sender_hash_salt,
    )


def _to_samples(
    selected: list[CandidatePair], sender_hash_salt: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, c in enumerate(selected):
        rows.append(
            {
                "question": c.question,
                "ground_truth": c.answer,
                "contexts": [],
                "metadata": {
                    "source": "Matrix Support Chat Export",
                    "protocol": c.protocol,
                    "protocol_confidence": c.protocol_confidence,
                    "staff_identity_hash": _hash_sender_identity(
                        c.answer_sender, salt=sender_hash_salt
                    ),
                    "question_ref_hash": _event_reference_hash(
                        c.question_event_id, sender_hash_salt=sender_hash_salt
                    ),
                    "answer_ref_hash": _event_reference_hash(
                        c.answer_event_id, sender_hash_salt=sender_hash_salt
                    ),
                    "sample_index": idx,
                },
            }
        )
    return rows


def _to_review(
    *,
    source_sha256: str,
    total_messages: int,
    extracted_candidates: int,
    selected: list[CandidatePair],
    selected_counts: dict[str, int],
    reject_counts: Counter[str],
    extra_rejections: list[dict[str, Any]],
    sender_hash_salt: str,
) -> dict[str, Any]:
    selected_rows = []
    for idx, c in enumerate(selected, start=1):
        selected_rows.append(
            {
                "review_id": f"matrix_eval_{idx:03d}",
                "review_status": "pending",
                "review_notes": "",
                "protocol": c.protocol,
                "protocol_confidence": c.protocol_confidence,
                "question": c.question,
                "ground_truth": c.answer,
                "staff_identity_hash": _hash_sender_identity(
                    c.answer_sender, salt=sender_hash_salt
                ),
                "question_ref_hash": _event_reference_hash(
                    c.question_event_id, sender_hash_salt=sender_hash_salt
                ),
                "answer_ref_hash": _event_reference_hash(
                    c.answer_event_id, sender_hash_salt=sender_hash_salt
                ),
                "quality_score": c.score,
            }
        )

    return {
        "metadata": {
            "generated_at": _now_iso(),
            "source": "sanitized_matrix_export",
            "source_sha256": source_sha256,
        },
        "statistics": {
            "total_messages": total_messages,
            "extracted_candidates": extracted_candidates,
            "selected_samples": len(selected_rows),
            "selected_by_protocol": selected_counts,
            "rejected_counts": dict(reject_counts),
        },
        "selected": selected_rows,
        "rejected_examples": [
            {
                **{
                    k: v
                    for k, v in row.items()
                    if k
                    not in {
                        "question_sender",
                        "answer_sender",
                        "question_event_id",
                        "answer_event_id",
                    }
                },
                "staff_identity_hash": _hash_sender_identity(
                    str(row.get("answer_sender", "")), salt=sender_hash_salt
                ),
                "question_ref_hash": _event_reference_hash(
                    str(row.get("question_event_id", "")),
                    sender_hash_salt=sender_hash_salt,
                ),
                "answer_ref_hash": _event_reference_hash(
                    str(row.get("answer_event_id", "")),
                    sender_hash_salt=sender_hash_salt,
                ),
            }
            for row in extra_rejections[:200]
        ],
    }


def _to_behavior_review(
    *,
    candidates: list[CandidatePair],
    source_sha256: str,
    missing_questions: list[MissingFAQQuestion],
    missing_faq_source_sha256: str | None,
    missing_match_threshold: float,
    sender_hash_salt: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (item.answer_ts, item.answer_event_id),
    ):
        answer_ref_hash = _event_reference_hash(
            candidate.answer_event_id,
            sender_hash_salt=sender_hash_salt,
        )
        behavior_labels = {
            "reviewed": False,
            "scam_warning_warranted": bool(SCAM_QUESTION_RE.search(candidate.question)),
            "staff_linked_wiki": bool(candidate.wiki_links),
            "troubleshooting": bool(TROUBLESHOOTING_RE.search(candidate.question)),
            "diagnostic_expected": candidate.is_diagnostic_reply,
            "remedy_terms": [REMEDY_TERMS[tag] for tag in candidate.remedy_tags],
        }
        rows.append(
            {
                "case_id": f"matrix_behavior_{answer_ref_hash[:16]}",
                "review_status": "pending",
                "review_notes": "",
                "question": candidate.question,
                "ground_truth": candidate.answer,
                "protocol": candidate.protocol,
                "protocol_confidence": candidate.protocol_confidence,
                "staff_identity_hash": _hash_sender_identity(
                    candidate.answer_sender, salt=sender_hash_salt
                ),
                "question_ref_hash": _event_reference_hash(
                    candidate.question_event_id,
                    sender_hash_salt=sender_hash_salt,
                ),
                "answer_ref_hash": answer_ref_hash,
                "wiki_links": list(candidate.wiki_links),
                "remedy_tags": list(candidate.remedy_tags),
                "reply_traits": {
                    "diagnostic": candidate.is_diagnostic_reply,
                    "link_only": candidate.is_link_only_reply,
                },
                "metadata": {
                    "protocol": candidate.protocol,
                    "protocol_confidence": candidate.protocol_confidence,
                    "behavior_labels": behavior_labels,
                },
                "missing_faq_match": _find_missing_faq_match(
                    candidate,
                    missing_questions,
                    threshold=missing_match_threshold,
                ),
            }
        )

    return {
        "schema_version": BEHAVIOR_SCHEMA_VERSION,
        "metadata": {
            "generated_at": _now_iso(),
            "source": "sanitized_matrix_export",
            "source_sha256": source_sha256,
            "review_required": True,
            "missing_faq_source_sha256": missing_faq_source_sha256,
            "missing_faq_match_threshold": missing_match_threshold,
        },
        "statistics": {
            "behavior_candidates": len(rows),
            "diagnostic_replies": sum(
                1 for row in rows if row["reply_traits"]["diagnostic"]
            ),
            "link_only_replies": sum(
                1 for row in rows if row["reply_traits"]["link_only"]
            ),
            "missing_faq_matches": sum(
                1 for row in rows if row["missing_faq_match"] is not None
            ),
        },
        "individual_results": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract Matrix Q/A benchmark and staff-behavior review samples"
    )
    parser.add_argument(
        "--input", default=DEFAULT_INPUT, help="Matrix export JSON path"
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Samples JSON output")
    parser.add_argument(
        "--review-output", default=DEFAULT_REVIEW, help="Review JSON output"
    )
    parser.add_argument(
        "--behavior-output",
        default=DEFAULT_BEHAVIOR_OUTPUT,
        help="Sanitized staff-behavior review JSON output",
    )
    parser.add_argument(
        "--missing-faq-input",
        default="",
        help="Optional sanitized missing-FAQ question JSON input",
    )
    parser.add_argument(
        "--missing-match-threshold",
        type=float,
        default=DEFAULT_MISSING_MATCH_THRESHOLD,
        help="Minimum deterministic lexical score for missing-FAQ matches (0.0-1.0)",
    )
    parser.add_argument("--max-samples", type=int, default=40)
    parser.add_argument(
        "--bisq1-ratio",
        type=float,
        default=0.60,
        help="Target ratio of multisig_v1 questions in selected set (0.0-1.0)",
    )
    parser.add_argument(
        "--include-unknown",
        action="store_true",
        help="Allow protocol=unknown samples if not enough protocol-tagged samples",
    )
    parser.add_argument(
        "--staff-ids",
        default="",
        help="Extra trusted staff Matrix IDs, comma-separated",
    )
    parser.add_argument(
        "--staff-localparts",
        default="",
        help=(
            "Explicit legacy opt-in for trusted staff localparts, comma-separated; "
            "prefer full --staff-ids to prevent homeserver impersonation"
        ),
    )
    parser.add_argument(
        "--sender-hash-salt",
        default="",
        help="Optional salt for anonymizing sender identities in output metadata.",
    )
    args = parser.parse_args()

    if not 0 <= args.bisq1_ratio <= 1:
        print("--bisq1-ratio must be between 0.0 and 1.0")
        return 2
    if not 0 <= args.missing_match_threshold <= 1:
        print("--missing-match-threshold must be between 0.0 and 1.0")
        return 2

    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    review_output_path = Path(args.review_output).expanduser().resolve()
    behavior_output_path = Path(args.behavior_output).expanduser().resolve()

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return 2

    with input_path.open(encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        messages = data.get("messages")
    elif isinstance(data, list):
        messages = data
    else:
        print("Unsupported input JSON format. Expected object or list.")
        return 2

    if not isinstance(messages, list):
        print("Input JSON does not contain a message list.")
        return 2

    staff_ids, staff_localparts = _build_staff_sets(args)
    detector = ProtocolDetector()

    candidates, behavior_candidates, reject_counts, rejected_examples = (
        extract_candidates(
            messages,
            staff_ids=staff_ids,
            staff_localparts=staff_localparts,
            detector=detector,
        )
    )

    missing_questions: list[MissingFAQQuestion] = []
    missing_faq_source_sha256: str | None = None
    if args.missing_faq_input:
        missing_faq_path = Path(args.missing_faq_input).expanduser().resolve()
        if not missing_faq_path.exists():
            print(f"Missing-FAQ input file not found: {missing_faq_path}")
            return 2
        try:
            missing_questions = _load_missing_faq_questions(
                missing_faq_path,
                sender_hash_salt=args.sender_hash_salt,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Invalid missing-FAQ input: {exc}")
            return 2
        missing_faq_source_sha256 = _file_sha256(missing_faq_path)

    selected, selected_counts = select_samples(
        candidates,
        max_samples=args.max_samples,
        bisq1_ratio=args.bisq1_ratio,
        include_unknown=args.include_unknown,
    )

    source_sha256 = _file_sha256(input_path)
    samples = _to_samples(selected, sender_hash_salt=args.sender_hash_salt)
    review = _to_review(
        source_sha256=source_sha256,
        total_messages=len(messages),
        extracted_candidates=len(candidates),
        selected=selected,
        selected_counts=selected_counts,
        reject_counts=reject_counts,
        extra_rejections=rejected_examples,
        sender_hash_salt=args.sender_hash_salt,
    )
    behavior_review = _to_behavior_review(
        candidates=behavior_candidates,
        source_sha256=source_sha256,
        missing_questions=missing_questions,
        missing_faq_source_sha256=missing_faq_source_sha256,
        missing_match_threshold=args.missing_match_threshold,
        sender_hash_salt=args.sender_hash_salt,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    review_output_path.parent.mkdir(parents=True, exist_ok=True)
    behavior_output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(samples, indent=2), encoding="utf-8")
    review_output_path.write_text(json.dumps(review, indent=2), encoding="utf-8")
    behavior_output_path.write_text(
        json.dumps(behavior_review, indent=2), encoding="utf-8"
    )

    print(f"Input: {input_path}")
    print(f"Candidates after filtering/dedup: {len(candidates)}")
    print(
        f"Behavior candidates before legacy answer filters: {len(behavior_candidates)}"
    )
    print(f"Selected samples: {len(samples)}")
    print(f"Selected protocol split: {selected_counts}")
    print(f"Samples output: {output_path}")
    print(f"Review output: {review_output_path}")
    print(f"Behavior review output: {behavior_output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

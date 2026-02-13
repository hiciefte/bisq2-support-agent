#!/usr/bin/env python3
"""Extract reviewable Matrix Q/A benchmark samples with protocol tagging.

This script reads a Matrix room export JSON and extracts staff-reply Q/A pairs.
It emits:
1) samples JSON usable by run_ragas_evaluation.py
2) review JSON with selection details and rejection reasons
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
from pathlib import Path
from typing import Any

# Keep import behavior aligned with other scripts in this repo.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.services.rag.protocol_detector import ProtocolDetector  # noqa: E402

DEFAULT_INPUT = "api/data/sample_matrix_messages.json"
DEFAULT_OUTPUT = "api/data/evaluation/matrix_realistic_qa_samples.json"
DEFAULT_REVIEW = "api/data/evaluation/matrix_realistic_qa_review.json"

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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_sender_identity(sender_id: str, *, salt: str) -> str:
    normalized = (sender_id or "").strip().lower()
    payload = f"{salt}matrix:{normalized}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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
    localparts: set[str] = set()

    trusted = getattr(settings, "TRUSTED_STAFF_IDS", []) or []
    if isinstance(trusted, str):
        trusted = [s.strip() for s in trusted.split(",") if s.strip()]
    for matrix_id in trusted:
        full_ids.add(matrix_id)
        localparts.add(_localpart(matrix_id))

    known_local = getattr(settings, "KNOWN_SUPPORT_STAFF", []) or []
    if isinstance(known_local, str):
        known_local = [s.strip() for s in known_local.split(",") if s.strip()]
    localparts.update(x.lower() for x in known_local if x)

    if args.staff_ids:
        full_ids.update([x.strip() for x in args.staff_ids.split(",") if x.strip()])
    if args.staff_localparts:
        localparts.update(
            [x.strip().lower() for x in args.staff_localparts.split(",") if x.strip()]
        )

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
) -> tuple[list[CandidatePair], Counter[str], list[dict[str, Any]]]:
    by_event_id = {
        str(m.get("event_id")): m
        for m in messages
        if isinstance(m, dict) and m.get("event_id")
    }

    messages_sorted = sorted(
        messages, key=lambda m: int(m.get("origin_server_ts") or 0)
    )

    candidates: list[CandidatePair] = []
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
        question = _norm_space(question_raw)
        answer = _clean_reply_body(answer_raw)

        if (
            len(question) < QUESTION_MIN_CHARS
            or len(question.split()) < QUESTION_MIN_WORDS
        ):
            rejects["question_too_short"] += 1
            continue
        if not _is_likely_standalone_question(question):
            rejects["question_not_standalone"] += 1
            continue
        if len(answer) < ANSWER_MIN_CHARS or len(answer.split()) < ANSWER_MIN_WORDS:
            rejects["answer_too_short"] += 1
            continue
        if _looks_like_link_only(answer):
            rejects["answer_link_only"] += 1
            continue
        if _looks_like_clarifying_answer(answer):
            rejects["answer_clarifying"] += 1
            continue

        protocol_detected, confidence = detector.detect_protocol_from_text(
            f"{question}\n\n{answer}"
        )
        protocol = protocol_detected or "unknown"
        score = _quality_score(question, answer, protocol, confidence)

        candidates.append(
            CandidatePair(
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
            )
        )

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
                    "answer_sender": c.answer_sender,
                }
            )

    return deduped, rejects, rejected_examples


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


def _to_samples(
    selected: list[CandidatePair], room_name: str, sender_hash_salt: str
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
                    "room_name": room_name,
                    "protocol": c.protocol,
                    "protocol_confidence": c.protocol_confidence,
                    "question_sender_hash": _hash_sender_identity(
                        c.question_sender, salt=sender_hash_salt
                    ),
                    "answer_sender_hash": _hash_sender_identity(
                        c.answer_sender, salt=sender_hash_salt
                    ),
                    "question_event_id": c.question_event_id,
                    "answer_event_id": c.answer_event_id,
                    "question_ts": c.question_ts,
                    "answer_ts": c.answer_ts,
                    "sample_index": idx,
                },
            }
        )
    return rows


def _to_review(
    *,
    input_path: str,
    room_name: str,
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
                "question_sender_hash": _hash_sender_identity(
                    c.question_sender, salt=sender_hash_salt
                ),
                "answer_sender_hash": _hash_sender_identity(
                    c.answer_sender, salt=sender_hash_salt
                ),
                "question_event_id": c.question_event_id,
                "answer_event_id": c.answer_event_id,
                "question_ts": c.question_ts,
                "answer_ts": c.answer_ts,
                "quality_score": c.score,
            }
        )

    return {
        "metadata": {
            "generated_at": _now_iso(),
            "source": input_path,
            "room_name": room_name,
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
            (
                {
                    **{
                        k: v
                        for k, v in row.items()
                        if k not in {"question_sender", "answer_sender"}
                    },
                    "question_sender_hash": _hash_sender_identity(
                        str(row.get("question_sender", "")), salt=sender_hash_salt
                    ),
                    "answer_sender_hash": _hash_sender_identity(
                        str(row.get("answer_sender", "")), salt=sender_hash_salt
                    ),
                }
            )
            for row in extra_rejections[:200]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract Matrix Q/A evaluation samples with Bisq1 coverage"
    )
    parser.add_argument(
        "--input", default=DEFAULT_INPUT, help="Matrix export JSON path"
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Samples JSON output")
    parser.add_argument(
        "--review-output", default=DEFAULT_REVIEW, help="Review JSON output"
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
        help="Extra trusted staff localparts, comma-separated",
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

    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    review_output_path = Path(args.review_output).expanduser().resolve()

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return 2

    with input_path.open(encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        messages = data.get("messages")
        room_name = str(data.get("room_name", ""))
    elif isinstance(data, list):
        messages = data
        room_name = ""
    else:
        print("Unsupported input JSON format. Expected object or list.")
        return 2

    if not isinstance(messages, list):
        print("Input JSON does not contain a message list.")
        return 2

    staff_ids, staff_localparts = _build_staff_sets(args)
    detector = ProtocolDetector()

    candidates, reject_counts, rejected_examples = extract_candidates(
        messages,
        staff_ids=staff_ids,
        staff_localparts=staff_localparts,
        detector=detector,
    )

    selected, selected_counts = select_samples(
        candidates,
        max_samples=args.max_samples,
        bisq1_ratio=args.bisq1_ratio,
        include_unknown=args.include_unknown,
    )

    samples = _to_samples(
        selected, room_name=room_name, sender_hash_salt=args.sender_hash_salt
    )
    review = _to_review(
        input_path=str(input_path),
        room_name=room_name,
        total_messages=len(messages),
        extracted_candidates=len(candidates),
        selected=selected,
        selected_counts=selected_counts,
        reject_counts=reject_counts,
        extra_rejections=rejected_examples,
        sender_hash_salt=args.sender_hash_salt,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    review_output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(samples, indent=2), encoding="utf-8")
    review_output_path.write_text(json.dumps(review, indent=2), encoding="utf-8")

    print(f"Input: {input_path}")
    print(f"Candidates after filtering/dedup: {len(candidates)}")
    print(f"Selected samples: {len(samples)}")
    print(f"Selected protocol split: {selected_counts}")
    print(f"Samples output: {output_path}")
    print(f"Review output: {review_output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

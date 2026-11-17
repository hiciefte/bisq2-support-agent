"""Prepare or execute a private, no-send replay of retained Staff conversations.

Preparation is entirely offline. Execution requires a frozen plan digest and an
explicit owner approval flag. It imports the same coordinator, request gate and
Staff draft service as live intake, but no Matrix client or retrieval service.
Saved document excerpts stand in for original retrieval; this is a counterfactual
input assumption, not a reconstruction of exact retrieval timestamps.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.channels.staff_assist.context_conversation import (
    MAX_EXCHANGE_TURNS,
    ConversationTurn,
    StaffConversationCoordinator,
    conversation_turn,
    selected_staff_request,
)
from app.channels.staff_assist.context_gate import (
    REQUEST_GATE_PROMPT,
    RequestGateService,
)
from app.channels.staff_assist.context_trial import (
    BudgetedContextLLM,
    ContextTrial,
    ContextTrialStore,
)
from app.channels.staff_assist.public_context import PublicEvidence, StaffEvidence
from app.channels.staff_assist.staff_context import StaffContextService
from app.channels.staff_assist.staff_prompt import STAFF_CONTEXT_PROMPT
from app.services.escalation.escalation_repository import EscalationRepository
from app.services.escalation.escalation_service import EscalationService

LIMITATION_OPENING = re.compile(
    r"^(?:(?:the\s+)?(?:available\s+)?(?:documentation|evidence|sources?)\s+"
    r"(?:does(?:n['’]t| not)|cannot|can['’]t|do(?:n['’]t| not))|"
    r"(?:I|we)\s+(?:cannot|can['’]t|do(?:n['’]t| not))\s+(?:determine|establish|confirm|tell)|"
    r"(?:the\s+)?(?:documentation|evidence)\s+(?:is insufficient|does not establish))",
    re.I,
)
ASSUMPTIONS = [
    "Retrospective two-hour partitions are input cohorts, not proven independent requests.",
    "Only observed events at or before each virtual quiet deadline are model inputs; later comparison replies are report-only.",
    "Saved document excerpts from an already-arrived source anchor stand in for original retrieval. Exact capture timestamps are unknown.",
    "Live/monitoring evidence requires an observation timestamp no later than virtual time; otherwise it is excluded.",
    "Recorded Staff labels reflect the collected configured-role mapping, not independently proved historical roles.",
    "Partial windows, missing relation targets and already-redacted original bodies remain coverage limitations.",
    "No fresh retrieval, embedding, provider tool, Matrix request or message send is part of this replay.",
    "The spend ledger bounds gate and draft model calls at approved price ceilings; it is not an invoice or all-provider-cost claim.",
    "Mechanical figures and AI-authored reference comparisons are not Staff quality verdicts, actual reuse or measured time savings.",
]


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_private(path: Path, value: Any) -> None:
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
    ) as stream:
        stream.write(json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def append_private(path: Path, value: Any) -> None:
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a"
    ) as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def timestamp_ms(value: Any) -> int | None:
    if type(value) is int:
        return value if value > 100_000_000_000 else value * 1000
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (
                int(parsed.timestamp() * 1000)
                if parsed.utcoffset() is not None
                else None
            )
        except ValueError:
            return None
    return None


def _event_core(message: dict[str, Any]) -> dict[str, Any]:
    original = (
        message.get("original_sanitized_event") or message.get("original_event") or {}
    )
    return {
        "event_id": message["event_id"],
        "sender": message.get("sender"),
        "origin_server_ts": message.get("origin_server_ts"),
        "role": message.get("role"),
        "content": original.get(
            "content",
            {"body": message.get("text", ""), "m.relates_to": message.get("relation")},
        ),
        "type": original.get("type", "m.room.message"),
        "redacts": original.get("redacts"),
    }


def load_inputs(plan_sources: dict[str, dict[str, str]]) -> dict[str, Any]:
    for source in plan_sources.values():
        if digest_bytes(Path(source["path"]).read_bytes()) != source["sha256"]:
            raise ValueError("Frozen replay input changed")
    cases = {row["id"]: row for row in read_jsonl(Path(plan_sources["cases"]["path"]))}
    threads = {
        row["case_id"]: row for row in read_jsonl(Path(plan_sources["threads"]["path"]))
    }
    index = json.loads(Path(plan_sources["sessions"]["path"]).read_text())
    for name, key in (("cases.jsonl", "cases"), ("threads.jsonl", "threads")):
        if index.get("source_hashes", {}).get(name) != plan_sources[key]["sha256"]:
            raise ValueError("Session partition does not match frozen source files")
    events: dict[tuple[str, str], dict[str, Any]] = {}
    conflicts: set[tuple[str, str]] = set()
    for case_id, thread in threads.items():
        room = (cases.get(case_id, {}).get("channel_metadata") or {}).get("room_id")
        if not room:
            continue
        for message in thread.get("messages", []):
            key = (room, message["event_id"])
            if key in events and _event_core(events[key]) != _event_core(message):
                conflicts.add(key)
            else:
                events[key] = message
    references = json.loads(Path(plan_sources["comparisons"]["path"]).read_text())
    return {
        "cases": cases,
        "threads": threads,
        "index": index,
        "events": events,
        "conflicts": conflicts,
        "comparisons": references,
    }


def saved_turn(room: str, message: dict[str, Any]) -> ConversationTurn:
    """Present the retained event to the same parser used by live subscription."""
    raw = dict(
        message.get("original_sanitized_event") or message.get("original_event") or {}
    )
    raw.setdefault(
        "content",
        {
            "body": message.get("text", ""),
            "msgtype": "m.text",
            "m.relates_to": message.get("relation"),
        },
    )
    content = raw["content"]
    event = SimpleNamespace(
        source=raw,
        event_id=message["event_id"],
        sender=message["sender"],
        server_timestamp=message["origin_server_ts"],
        body=content.get("body", message.get("text", "")),
        redacts=raw.get("redacts") or content.get("redacts"),
    )
    return conversation_turn(
        room,
        event,
        is_staff=message.get("role") == "staff",
        is_bot=message.get("role") in {"assistant", "bot"},
    )


def session_turns(
    session: dict[str, Any], inputs: dict[str, Any]
) -> tuple[list[ConversationTurn], list[str]]:
    turns, limitations = [], []
    for candidate in session["candidate_events"]:
        key = (session["room_id"], candidate["event_id"])
        if key in inputs["conflicts"]:
            limitations.append("conflicting_saved_event:" + candidate["event_id"])
            continue
        message = inputs["events"].get(key)
        if message is None:
            limitations.append("missing_saved_event:" + candidate["event_id"])
            continue
        if type(message.get("origin_server_ts")) is not int:
            limitations.append("missing_event_time:" + candidate["event_id"])
            continue
        original = message.get("original_sanitized_event") or {}
        if (original.get("unsigned") or {}).get("redacted_because"):
            limitations.append(
                "original_body_already_redacted:" + candidate["event_id"]
            )
        turns.append(saved_turn(session["room_id"], message))
    unique = {turn.event_id: turn for turn in turns}
    return sorted(
        unique.values(), key=lambda turn: (turn.timestamp_ms, turn.event_id)
    ), sorted(set(limitations))


def evidence_at(
    session: dict[str, Any], now_ms: int, inputs: dict[str, Any]
) -> tuple[list[Any], dict[str, Any]]:
    """Reuse the latest arrived anchor's original snapshot, never a future case."""
    eligible = [
        item
        for item in session["anchors"]
        if item["origin_server_ts"] <= now_ms
        and (inputs["cases"][item["case_id"]].get("channel_metadata") or {}).get(
            "evidence_snapshot"
        )
    ]
    if not eligible:
        return [], {
            "source_case_id": None,
            "assumption": "no_saved_evidence_for_arrived_anchor",
            "excluded": [],
        }
    anchor = max(eligible, key=lambda item: (item["origin_server_ts"], item["case_id"]))
    snapshot = inputs["cases"][anchor["case_id"]]["channel_metadata"][
        "evidence_snapshot"
    ]
    evidence, excluded, unavailable_urls = [], [], []
    for raw in snapshot:
        kind = raw.get("kind")
        provenance = raw.get("provenance") or {}
        observed = next(
            (
                timestamp_ms(provenance[key])
                for key in (
                    "observed_at",
                    "captured_at",
                    "timestamp",
                    "fetched_at",
                    "observation_time",
                )
                if timestamp_ms(provenance.get(key)) is not None
            ),
            None,
        )
        live = kind in {"live_tool", "monitoring"}
        if (observed is not None and observed > now_ms) or (live and observed is None):
            excluded.append(
                {
                    "source_id": raw.get("id"),
                    "reason": "future_or_unproved_observation_time",
                }
            )
            continue
        try:
            item = (
                StaffEvidence.model_validate(raw)
                if raw.get("audience") == "staff_only"
                else PublicEvidence.model_validate(raw)
            )
        except ValueError:
            # Sanitization can intentionally make a URL unusable. Retain source
            # text honestly as a saved excerpt, without inventing a public link.
            try:
                item = StaffEvidence(
                    id=raw["id"],
                    title=raw["title"],
                    content=raw["content"],
                    kind="saved_excerpt",
                    source_refs=[],
                    provenance={
                        "original_kind": kind,
                        "original_url_unavailable": True,
                        "source_case_id": anchor["case_id"],
                        "counterfactual_saved_retrieval": True,
                    },
                )
            except (KeyError, ValueError):
                excluded.append(
                    {"source_id": raw.get("id"), "reason": "invalid_saved_evidence"}
                )
                continue
            unavailable_urls.append(raw["id"])
        evidence.append(item)
    return evidence, {
        "source_case_id": anchor["case_id"],
        "assumption": "saved_document_excerpts_from_arrived_anchor; exact_capture_time_unknown",
        "excluded": excluded,
        "unavailable_public_urls": unavailable_urls,
    }


def model_code_hashes() -> dict[str, str]:
    base = Path(__file__).resolve().parents[1]
    paths = [
        "channels/staff_assist/" + name
        for name in (
            "context_conversation.py",
            "context_gate.py",
            "context_trial.py",
            "staff_context.py",
            "staff_prompt.py",
            "public_context.py",
        )
    ]
    paths.extend(
        [
            "scripts/replay_staff_context.py",
            "scripts/summarize_staff_context.py",
            "services/rag/openai_responses.py",
            "channels/ingress/service.py",
            "channels/plugins/matrix/context_text.py",
            "channels/staff_assist/context_incidents.py",
        ]
    )
    return {path: digest_bytes((base / path).read_bytes()) for path in paths}


def validate_limits(args: argparse.Namespace) -> None:
    for field in (
        "budget_usd",
        "daily_budget_usd",
        "input_usd_per_million",
        "output_usd_per_million",
    ):
        try:
            value = Decimal(getattr(args, field))
        except (InvalidOperation, TypeError):
            raise ValueError(
                "Replay prices and budgets must be explicit positive decimals"
            ) from None
        if not value.is_finite() or value <= 0:
            raise ValueError(
                "Replay prices and budgets must be explicit positive decimals"
            )
    if Decimal(args.daily_budget_usd) > Decimal(args.budget_usd):
        raise ValueError("Daily budget cannot exceed replay budget")
    if not 1 <= args.max_output_tokens <= 32768:
        raise ValueError("Invalid output-token limit")
    if not 1 <= args.max_model_calls <= 10000:
        raise ValueError("Invalid model-call limit")
    if not 1 <= args.maximum_elapsed_seconds <= 86400:
        raise ValueError("Replay must have a finite, at most one-day execution window")
    if not 0 < args.first_response_delay_seconds <= 86400:
        raise ValueError("Invalid quiet delay")
    if not isinstance(args.model, str) or not args.model.strip():
        raise ValueError("Explicit model required")


def recorded_usage_reference(
    inputs: dict[str, Any], args: argparse.Namespace
) -> dict[str, Any]:
    cohort_ids = {
        case_id
        for session in inputs["index"]["sessions"]
        for case_id in session["case_ids"]
    }
    usages = []
    for case_id in cohort_ids:
        usage = (inputs["cases"][case_id].get("channel_metadata") or {}).get(
            "model_usage"
        )
        if isinstance(usage, dict) and all(
            type(usage.get(key)) is int and usage[key] >= 0
            for key in ("prompt_tokens", "completion_tokens")
        ):
            usages.append(usage)
    input_tokens = sum(row["prompt_tokens"] for row in usages)
    output_tokens = sum(row["completion_tokens"] for row in usages)
    cost = (
        Decimal(input_tokens) * Decimal(args.input_usd_per_million)
        + Decimal(output_tokens) * Decimal(args.output_usd_per_million)
    ) / 1000000
    mean = cost / len(usages) if usages else None
    cohorts = len(inputs["index"]["sessions"])
    return {
        "observed_cohort_calls": len(usages),
        "observed_input_tokens": input_tokens,
        "observed_output_tokens": output_tokens,
        "cost_at_proposed_ceiling_rates_usd": str(cost),
        "mean_cost_per_recorded_call_usd": str(mean) if mean is not None else None,
        "illustrative_two_calls_per_cohort_usd": (
            str(mean * 2 * cohorts) if mean is not None else None
        ),
        "illustrative_four_calls_per_cohort_usd": (
            str(mean * 4 * cohorts) if mean is not None else None
        ),
        "limitation": "Historical note sizes are a reference, not a forecast: new attributed conversations, separate gates and output contract differ. These illustrative totals neither guarantee completion nor authorize spend.",
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    validate_limits(args)
    paths = {
        "cases": args.cases,
        "threads": args.threads,
        "sessions": args.sessions,
        "comparisons": args.comparisons,
        "examples": args.data_dir / "staff-context-examples.json",
    }
    sources = {
        key: {"path": str(path.resolve()), "sha256": digest_bytes(path.read_bytes())}
        for key, path in paths.items()
    }
    inputs = load_inputs(sources)
    if not inputs["index"].get("sessions"):
        raise ValueError("Replay requires at least one retained input cohort")
    examples = StaffContextService(None, data_dir=args.data_dir)
    if examples.examples_source != "private_file":
        raise ValueError("Replay requires the reviewed private example file")
    estimates = []
    for session in inputs["index"]["sessions"]:
        turns, limitations = session_turns(session, inputs)
        # Bounding envelope: all saved attributed turns and arrived document
        # snapshots in the cohort. Actual gate selection may use less context.
        available = [
            evidence_at(session, anchor["origin_server_ts"], inputs)[0]
            for anchor in session["anchors"]
        ]
        widest_evidence = max(
            available,
            key=lambda items: len(
                json.dumps([item.model_dump() for item in items], ensure_ascii=False)
            ),
            default=[],
        )
        envelope = {
            "turns": [asdict(turn) for turn in turns],
            "evidence": [item.model_dump() for item in widest_evidence],
            "style_examples": examples.examples,
        }
        # A descriptive input estimate, not an admission guarantee: updates may
        # repeat the prior snapshot and global context may exceed this cohort.
        # The independent 100,000-byte runtime limit is the absolute call bound.
        token_envelope = (
            2 * len(json.dumps(envelope, ensure_ascii=False).encode())
            + max(len(REQUEST_GATE_PROMPT.encode()), len(STAFF_CONTEXT_PROMPT.encode()))
            + 4096
        )
        token_ceiling = min(100000, token_envelope)
        call_ceiling = (
            Decimal(token_ceiling) * Decimal(args.input_usd_per_million) / 1000000
            + Decimal(args.max_output_tokens)
            * Decimal(args.output_usd_per_million)
            / 1000000
        )
        focal_turns = sum(
            turn.sender_id == session["requester_id"]
            and session["first_anchor_ms"]
            <= turn.timestamp_ms
            <= session["last_anchor_ms"]
            for turn in turns
        )
        estimates.append(
            {
                "session_id": session["session_id"],
                "case_ids": session["case_ids"],
                "candidate_event_count": len(turns),
                "focal_event_count": focal_turns,
                "input_token_envelope": token_envelope,
                "exceeds_runtime_input_bound": token_envelope > 100000,
                "per_call_conservative_usd": str(call_ceiling),
                "limitations": limitations,
                "coverage": session.get("case_window_coverage"),
            }
        )
    maximum = max(
        (Decimal(item["per_call_conservative_usd"]) for item in estimates),
        default=Decimal(0),
    )
    plan = {
        "schema_version": 1,
        "mode": "pending_owner_approval",
        "sources": sources,
        "code_sha256": model_code_hashes(),
        "data_dir": str(args.data_dir.resolve()),
        "examples_sha256": examples.examples_sha256,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "max_output_tokens": args.max_output_tokens,
        "input_usd_per_million_ceiling": args.input_usd_per_million,
        "output_usd_per_million_ceiling": args.output_usd_per_million,
        "budget_usd": args.budget_usd,
        "daily_budget_usd": args.daily_budget_usd,
        "max_model_calls": args.max_model_calls,
        "maximum_elapsed_seconds": args.maximum_elapsed_seconds,
        "first_response_delay_seconds": args.first_response_delay_seconds,
        "assumptions": ASSUMPTIONS,
        "session_count": len(estimates),
        "natural_case_count": inputs["index"]["natural_case_count"],
        "distinct_room_requester_pairs": inputs["index"][
            "distinct_room_requester_pairs"
        ],
        "source_partition_discrepancy": inputs["index"].get("discrepancy"),
        "sessions": estimates,
        "estimate": {
            "largest_prepared_call_envelope_usd": str(maximum),
            "all_maximum_calls_at_largest_envelope_usd": str(
                maximum * args.max_model_calls
            ),
            "proposed_model_spend_ceiling_usd": args.budget_usd,
            "absolute_input_token_bound_per_call": 100000,
            "absolute_per_call_cost_ceiling_usd": str(
                Decimal(100000) * Decimal(args.input_usd_per_million) / 1000000
                + Decimal(args.max_output_tokens)
                * Decimal(args.output_usd_per_million)
                / 1000000
            ),
            "absolute_all_maximum_calls_cost_usd": str(
                args.max_model_calls
                * (
                    Decimal(100000) * Decimal(args.input_usd_per_million) / 1000000
                    + Decimal(args.max_output_tokens)
                    * Decimal(args.output_usd_per_million)
                    / 1000000
                )
            ),
            "recorded_usage_reference": recorded_usage_reference(inputs, args),
            "actual_calls_and_total_unknown": True,
            "note": "The ledger stops before any next call cannot fit; a small budget can yield an incomplete replay. Input envelopes are estimates; exact runtime byte bounds govern admission.",
        },
        "comparison_status": "after_values_pending_paid_execution_and_separate_agent_review; no_staff_verdicts",
    }
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    write_private(args.output / "plan.json", plan)
    write_private(
        args.output / "prepared-report.json",
        report_data(plan, inputs, [], [], pending=True),
    )
    (args.output / "REPORT.md").write_text(
        render_report(report_data(plan, inputs, [], [], pending=True))
    )
    os.chmod(args.output / "REPORT.md", 0o600)
    return {
        "plan": str(args.output / "plan.json"),
        "plan_sha256": digest_bytes((args.output / "plan.json").read_bytes()),
        "sessions": plan["session_count"],
        "paid_calls": 0,
        "estimate": plan["estimate"],
    }


def report_data(
    plan: dict[str, Any],
    inputs: dict[str, Any],
    generations: list[dict[str, Any]],
    formed: list[dict[str, Any]],
    *,
    pending: bool,
    stopped: str | None = None,
) -> dict[str, Any]:
    reference_counts = Counter(
        row["reference_category"] for row in generations if row.get("model_called")
    )
    assessed = reference_counts["request"] + reference_counts["non_request"]
    replies = [row for row in generations if row.get("reply") and row.get("rendered")]
    limitation_count = sum(
        bool(LIMITATION_OPENING.search(row["reply"].strip())) for row in replies
    )
    comparisons = []
    for reference in inputs["comparisons"]["cases"]:
        generated = [
            row
            for row in generations
            if reference["case_id"] in row.get("source_case_ids", [])
            and row.get("rendered")
        ]
        first = generated[0] if generated else None
        comparisons.append(
            {
                **reference,
                "after_action_present": None,
                "after_reply": first.get("reply") if first else None,
                "after_virtual_time_ms": (
                    first.get("virtual_time_ms") if first else None
                ),
                "comparison_status": (
                    "pending_paid_replay"
                    if pending
                    else (
                        "agent_action_comparison_required"
                        if first
                        else "no_generated_reply_to_compare"
                    )
                ),
                "is_staff_quality_verdict": False,
            }
        )
    examples = []
    for case_id in inputs["comparisons"]["focus_case_ids"]:
        case = inputs["cases"].get(case_id, {})
        metadata = case.get("channel_metadata") or {}
        rows = [row for row in generations if case_id in row.get("source_case_ids", [])]
        examples.append(
            {
                "case_id": case_id,
                "before": (metadata.get("model_decision") or {}).get("text"),
                "after": rows[0].get("reply") if rows else None,
                "after_attempts": rows,
                "attempt_summary": [
                    {
                        "kind": row.get("kind", "note"),
                        "virtual_time_ms": row.get("virtual_time_ms"),
                        "action": (row.get("preview", {}).get("decision") or {}).get(
                            "action", "unknown"
                        ),
                        "rendered": row.get("rendered", False),
                        "reply": row.get("reply"),
                        "input_event_ids": row.get("input_event_ids", []),
                    }
                    for row in rows
                ],
                "status": (
                    "pending_paid_replay"
                    if pending
                    else "generated" if rows else "no_draft_attempt"
                ),
            }
        )
    return {
        "status": (
            "pending_owner_approval"
            if pending
            else "stopped" if stopped else "executed_pending_agent_and_staff_review"
        ),
        "stopped_reason": stopped,
        "assumptions": plan["assumptions"],
        "baseline": inputs["comparisons"]["baseline"],
        "after": {
            "cases_formed": None if pending else len(formed),
            "model_note_generations": (
                None
                if pending
                else sum(bool(row.get("model_called")) for row in generations)
            ),
            "rendered_replies": None if pending else len(replies),
            "non_request_generations": (
                None if pending else reference_counts["non_request"]
            ),
            "reference_assessed_generations": None if pending else assessed,
            "reference_unassessed_generations": (
                None if pending else reference_counts["unassessed"]
            ),
            "non_request_share_on_assessed_subset": (
                (reference_counts["non_request"] / assessed)
                if not pending and assessed
                else None
            ),
            "limitation_openings": None if pending else limitation_count,
            "limitation_opening_share": (
                limitation_count / len(replies) if replies and not pending else None
            ),
            "staff_verdicts": None,
            "actual_reuse": None,
            "measured_time_saved": None,
        },
        "reference_rules": "Only the supplied private reference labels are fixed references. A selected conversation containing a labelled request is a request; all selected anchors must be known non-requests to call it a non-request. Other/mixed unknown cases stay unassessed. Gate predictions are never used as ground truth.",
        "before_after": examples,
        "action_comparisons": comparisons,
        "formed_cases": formed,
        "input_coverage": {
            "cohort_count": plan.get("session_count"),
            "natural_anchor_count": plan.get("natural_case_count"),
            "recorded_room_requester_pairs": plan.get("distinct_room_requester_pairs"),
            "source_partition_discrepancy": plan.get("source_partition_discrepancy"),
            "case_window_status_counts": dict(
                Counter(
                    coverage.get("status", "unknown")
                    for session in plan.get("sessions", [])
                    for coverage in (session.get("coverage") or [])
                    if isinstance(coverage, dict)
                )
            ),
        },
        "estimate": plan["estimate"],
    }


def render_report(report: dict[str, Any]) -> str:
    after, baseline = report["after"], report["baseline"]

    def display(value: Any) -> str:
        return "Pending / unmeasured" if value is None else str(value)

    lines = [
        "# Staff-context chronological replay",
        "",
        f"Status: {report['status']}",
        "",
        "These are conversation and drafting mechanics, not Staff quality verdicts.",
        "",
        "| Measure | Pilot reference | Replay |",
        "|---|---:|---:|",
        f"| Cases formed | {baseline['cases']} from {baseline['sessions']} retrospective sessions | {display(after['cases_formed'])} |",
        f"| Model note generations | {baseline['real_model_calls']} | {display(after['model_note_generations'])} |",
        f"| Non-request share (replay: assessed subset only) | {baseline['non_request_model_calls']}/{baseline['real_model_calls']} (review reading) | {display(after['non_request_share_on_assessed_subset'])} |",
        f"| Fixed-reference coverage | Explicit private reference labels | {display(after['reference_assessed_generations'])} assessed; {display(after['reference_unassessed_generations'])} unassessed |",
        f"| Replies opening with a limitation (heuristic) | {baseline['limitation_openings']}/{baseline['notes_written']} | {display(after['limitation_openings'])} / {display(after['rendered_replies'])} |",
        "| Staff verdicts / actual reuse / measured savings | Not recorded | Unmeasured |",
        "",
        "## Coverage and assumptions",
        "",
    ]
    lines += ["- " + item for item in report["assumptions"]]
    if "chronological_coverage" in report:
        lines += [
            "",
            "Chronological execution coverage: "
            + json.dumps(report["chronological_coverage"], sort_keys=True),
            "A stopped partial run is not a full-cohort result.",
            "",
        ]
    lines += [
        "",
        "Input coverage: " + json.dumps(report["input_coverage"], sort_keys=True),
        "",
    ]
    lines += ["", report["reference_rules"], "", "## Before and after", ""]
    for item in report["before_after"]:
        lines += [
            f"### Case {item['case_id']}",
            "",
            "Before:",
            "",
            item["before"] or "No retained draft.",
            "",
            "After attempts:",
            "",
        ]
        if not item["attempt_summary"]:
            lines += [
                (
                    "Pending paid execution."
                    if item["status"] == "pending_paid_replay"
                    else "No draft attempt recorded; no after answer is assessed."
                ),
                "",
            ]
        for index, attempt in enumerate(item["attempt_summary"]):
            at = attempt["virtual_time_ms"]
            stamp = (
                datetime.fromtimestamp(at / 1000, timezone.utc).isoformat()
                if isinstance(at, int)
                else "unknown virtual time"
            )
            lines += [
                f"{'Initial attempt' if index == 0 else 'Subsequent attempt'} ({attempt['kind']}) at {stamp}: action={attempt['action']}; rendered={attempt['rendered']}.",
                "",
                attempt["reply"]
                or "No reply text (silence or rejected output; see retained attempt diagnostic).",
                "",
            ]
            if index:
                lines += [
                    "This update uses facts available at its later virtual time; it is not the initial answer.",
                    "",
                ]
    lines += [
        "## Action comparisons",
        "",
        "Reference answers remain report-only and never enter generation prompts. Action agreement requires a separate reading; it is not a Staff verdict.",
        "",
        "| Case | Reference role | Action agreement | Status |",
        "|---|---|---|---|",
    ]
    for item in report["action_comparisons"]:
        lines.append(
            f"| {item['case_id']} | {item.get('comparison_role', 'unknown')} | Unassessed | {item['comparison_status']} |"
        )
    lines += ["", "## Cost", "", json.dumps(report["estimate"], indent=2), ""]
    if "model_usage_by_kind" in report:
        lines += [
            "Observed usage and conservative held reservations (one USD = 1,000,000,000 nanodollars):",
            "",
            json.dumps(report["model_usage_by_kind"], indent=2),
            "",
        ]
    if report.get("capacity_limited_snapshots"):
        lines += [
            f"Capacity-limited snapshots: {len(report['capacity_limited_snapshots'])}; unassessed, with no oversized provider attempt.",
            "",
        ]
    if report.get("stopped_reason"):
        lines += [
            "Stopped: " + report["stopped_reason"],
            "Do not retry or resume ambiguous provider calls.",
            "",
        ]
    return "\n".join(lines)


class ReplayCalls:
    def __init__(
        self, plan: dict[str, Any], llm: Any, store: ContextTrialStore, output: Path
    ):
        self.plan, self.llm, self.store, self.output = plan, llm, store, output
        self.started = time.monotonic()
        self.calls = 0

    def adapter(
        self, snapshot: Any, *, kind: str, virtual_time_ms: int
    ) -> BudgetedContextLLM:
        call_id = snapshot.version

        def before_call() -> str | None:
            if self.calls >= self.plan["max_model_calls"]:
                return "replay_model_call_cap_reached"
            if time.monotonic() - self.started >= self.plan["maximum_elapsed_seconds"]:
                return "replay_elapsed_limit_reached"
            append_private(
                self.output / "call-intents.jsonl",
                {
                    "case_id": snapshot.case_id,
                    "kind": kind,
                    "call_id": call_id,
                    "virtual_time_ms": virtual_time_ms,
                    "status": "started_or_uncertain",
                    "model": self.plan["model"],
                },
            )
            self.calls += 1
            return None

        return BudgetedContextLLM(
            self.store,
            self.llm,
            snapshot.case_id,
            kind=kind,
            call_id=call_id,
            before_call=before_call,
        )


def _source_cases(
    snapshot: Any, selected_ids: list[str], inputs: dict[str, Any]
) -> list[int]:
    selected = set(selected_ids)
    # Effective author edits replace the event in the prompt, but the original
    # source anchor still owns the report-only reference. Never add unselected
    # neighboring messages or infer quote/thread membership here.
    selected.update(
        turn.replaces_event_id
        for turn in snapshot.turns
        if turn.event_id in selected_ids and turn.replaces_event_id
    )
    return sorted(
        {
            anchor["case_id"]
            for session in inputs["index"]["sessions"]
            if session["room_id"] == snapshot.room_id
            and session["requester_id"] == snapshot.requester_id
            for anchor in session["anchors"]
            if anchor["event_id"] in selected
        }
    )


def _reference_category(case_ids: list[int], references: dict[str, Any]) -> str:
    requests = set(references["reference_request_ids"])
    non_requests = set(references["reference_non_request_ids"])
    if any(case_id in requests for case_id in case_ids):
        return "request"
    if case_ids and all(case_id in non_requests for case_id in case_ids):
        return "non_request"
    return "unassessed"


def ordered_turns(
    inputs: dict[str, Any], delay_ms: int
) -> tuple[list[ConversationTurn], int, list[dict[str, Any]]]:
    sessions = inputs["index"]["sessions"]
    end_ms = max(session["last_anchor_ms"] for session in sessions) + delay_ms
    event_map, limitations = {}, []
    for session in sessions:
        turns, gaps = session_turns(session, inputs)
        limitations.extend(
            {"session_id": session["session_id"], "limitation": gap} for gap in gaps
        )
        for turn in turns:
            if turn.timestamp_ms <= end_ms:
                event_map[(turn.room_id, turn.event_id)] = turn
    ordered = sorted(
        event_map.values(),
        key=lambda turn: (turn.timestamp_ms, turn.room_id, turn.event_id),
    )
    return ordered, end_ms, limitations


def hydrate_recent(
    coordinator: StaffConversationCoordinator, consumed: list[ConversationTurn]
) -> None:
    """Restore only bounded in-memory neighbors; never replay case transitions."""
    for turn in consumed:
        if turn.is_bot:
            continue
        recent = coordinator._recent.setdefault(turn.room_id, [])
        if not any(item.event_id == turn.event_id for item in recent):
            recent.append(turn)
            del recent[:-MAX_EXCHANGE_TURNS]


async def replay(
    plan: dict[str, Any],
    inputs: dict[str, Any],
    output: Path,
    calls: ReplayCalls,
    *,
    continuation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repository = EscalationRepository(calls.store.db_path)
    await repository.initialize()
    service = EscalationService(
        repository, None, None, None, SimpleNamespace(ESCALATION_CLAIM_TTL_MINUTES=30)
    )
    coordinator = StaffConversationCoordinator(
        service,
        calls.store.trial.trial_id,
        first_response_delay_seconds=plan["first_response_delay_seconds"],
    )
    sessions = inputs["index"]["sessions"]
    delay_ms = int(plan["first_response_delay_seconds"] * 1000)
    ordered, end_ms, limitations = ordered_turns(inputs, delay_ms)
    formed, generations, gates, capacity_limited = [], [], [], []
    skipped_versions: set[tuple[int, str]] = set()
    last_time = ordered[0].timestamp_ms if ordered else 0
    stopped = None
    processed_event_count = 0
    if continuation is not None:
        processed_event_count = continuation["processed_event_count"]
        last_time = continuation["last_time"]
        formed = list(continuation["formed_cases"])
        generations = list(continuation["drafts"])
        gates = list(continuation["gates"])
        capacity_limited = list(continuation.get("capacity_limited_snapshots", []))
        hydrate_recent(coordinator, ordered[:processed_event_count])
    skipped_versions.update(
        (row["case_id"], row["snapshot_version"]) for row in capacity_limited
    )

    async def run_due(until: int) -> None:
        nonlocal last_time, stopped
        pending = await coordinator.due(now_ms=until)
        for initial in sorted(
            pending, key=lambda row: (row.last_requester_at_ms + delay_ms, row.case_id)
        ):
            virtual = max(last_time, initial.last_requester_at_ms + delay_ms)
            if virtual > until:
                continue
            snapshot = await coordinator.snapshot(initial.case_id, now_ms=virtual)
            if (
                snapshot.case_id,
                snapshot.version,
            ) in skipped_versions or not await coordinator.claim(snapshot):
                continue
            gate_llm = calls.adapter(snapshot, kind="gate", virtual_time_ms=virtual)
            gate_service = RequestGateService(gate_llm)
            failed = False
            note_llm = None
            try:
                gate = await asyncio.to_thread(gate_service.classify, snapshot)
                gate_row = {
                    "case_id": snapshot.case_id,
                    "snapshot_version": snapshot.version,
                    "virtual_time_ms": virtual,
                    "input_event_ids": [turn.event_id for turn in snapshot.turns],
                    "omitted_optional_event_ids": list(
                        getattr(snapshot, "omitted_event_ids", ())
                    ),
                    "decision": gate.model_dump(),
                    "usage": gate_service.usage,
                }
                append_private(output / "gates.jsonl", gate_row)
                gates.append(gate_row)
                await coordinator.record_gate(snapshot, gate)
                if not snapshot.should_draft(gate):
                    continue
                matching = [
                    session
                    for session in sessions
                    if session["room_id"] == snapshot.room_id
                    and session["requester_id"] == snapshot.requester_id
                    and session["first_anchor_ms"] <= virtual
                ]
                if not matching:
                    raise ValueError("Replay request has no input cohort")
                cohort = max(matching, key=lambda session: session["first_anchor_ms"])
                evidence, evidence_coverage = evidence_at(cohort, virtual, inputs)
                request = selected_staff_request(snapshot, gate, evidence)
                note_llm = calls.adapter(
                    snapshot, kind=snapshot.kind, virtual_time_ms=virtual
                )
                preview = await asyncio.to_thread(
                    StaffContextService(note_llm, data_dir=plan["data_dir"]).preview,
                    request,
                )
                if note_llm.reason:
                    raise ValueError(note_llm.reason)
                source_cases = _source_cases(snapshot, gate.selected_event_ids, inputs)
                row = {
                    "case_id": snapshot.case_id,
                    "kind": snapshot.kind,
                    "virtual_time_ms": virtual,
                    "snapshot_version": snapshot.version,
                    "input_event_ids": gate.selected_event_ids,
                    "omitted_optional_event_ids": list(
                        getattr(snapshot, "omitted_event_ids", ())
                    ),
                    "source_case_ids": source_cases,
                    "reference_category": _reference_category(
                        source_cases, inputs["comparisons"]
                    ),
                    "evidence_coverage": evidence_coverage,
                    "model_called": preview.model_called,
                    "rendered": bool(preview.rendered_note),
                    "reply": preview.decision.reply,
                    "preview": preview.model_dump(),
                }
                generations.append(row)
                append_private(output / "drafts.jsonl", row)
                await coordinator.record_draft(
                    snapshot, preview, selected_event_ids=gate.selected_event_ids
                )
                if preview.decision.reason == "generation_unavailable":
                    raise ValueError("provider_outcome_unknown")
            except Exception as exc:
                reason = getattr(note_llm, "reason", None) or gate_llm.reason
                if reason is None:
                    reason = (
                        str(exc)
                        if type(exc).__name__ == "RequestGateError"
                        else type(exc).__name__
                    )
                capacity = reason in {
                    "conversation_input_capacity_reached",
                    "context_trial_invalid_call_bound",
                }
                failed = not capacity
                if capacity:
                    item = {
                        "case_id": snapshot.case_id,
                        "snapshot_version": snapshot.version,
                        "virtual_time_ms": virtual,
                        "reason": reason,
                        "assessment": "unassessed_capacity_limited",
                    }
                    capacity_limited.append(item)
                    append_private(output / "capacity-limited.jsonl", item)
                    skipped_versions.add((snapshot.case_id, snapshot.version))
                    continue
                stopped = reason
                append_private(
                    output / "failures.jsonl",
                    {
                        "case_id": snapshot.case_id,
                        "virtual_time_ms": virtual,
                        "kind": "gate_or_draft",
                        "reason": reason,
                        "raw_output": getattr(exc, "raw", None),
                        "usage": getattr(exc, "usage", None),
                    },
                )
                raise
            finally:
                # A failed run is never resumed, regardless of whether transport
                # was proved absent; its durable call ledger remains intact.
                await coordinator.finish(snapshot, uncertain=failed)
            last_time = virtual

    try:
        position = processed_event_count
        while position < len(ordered):
            timestamp = ordered[position].timestamp_ms
            await run_due(timestamp - 1)
            group = []
            while (
                position < len(ordered) and ordered[position].timestamp_ms == timestamp
            ):
                group.append(ordered[position])
                position += 1
            for turn in group:
                allow_new = any(
                    session["room_id"] == turn.room_id
                    and session["requester_id"] == turn.sender_id
                    and session["first_anchor_ms"]
                    <= timestamp
                    <= session["last_anchor_ms"]
                    for session in sessions
                )
                intake = await coordinator.ingest(
                    turn, now_ms=timestamp, allow_new=allow_new
                )
                processed_event_count += 1
                if intake.created:
                    formed.append(
                        {
                            "case_id": intake.case_id,
                            "source_event_id": turn.event_id,
                            "room_id": turn.room_id,
                            "requester_id": turn.sender_id,
                            "created_virtual_time_ms": timestamp,
                        }
                    )
            last_time = timestamp
            await run_due(timestamp)
        await run_due(end_ms)
    except Exception as exc:
        # Do not log provider bodies. Exact outputs returned by the gate/service
        # are private artifacts; provider exception content is never persisted.
        stopped = stopped or type(exc).__name__
    result = report_data(
        plan, inputs, generations, formed, pending=False, stopped=stopped
    )
    result["chronological_coverage"] = {
        "planned_observed_events": len(ordered),
        "processed_observed_events": processed_event_count,
        "reached_final_quiet_deadline": stopped is None,
        "planned_final_virtual_time_ms": end_ms,
        "last_processed_virtual_time_ms": last_time,
    }
    result["gate_calls_recorded"] = len(gates)
    result["provider_invocations_started_or_uncertain"] = calls.calls
    result["event_coverage_limitations"] = limitations
    result["capacity_limited_snapshots"] = capacity_limited
    result["no_matrix_requests_or_sends"] = True
    return result


def approved_plan(
    path: Path, approved_sha256: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    data = path.read_bytes()
    if digest_bytes(data) != approved_sha256:
        raise ValueError("Approved plan hash does not match")
    plan = json.loads(data)
    if plan["code_sha256"] != model_code_hashes():
        raise ValueError("Reviewed replay code changed; prepare and approve a new plan")
    inputs = load_inputs(plan["sources"])
    if (
        StaffContextService(None, data_dir=plan["data_dir"]).examples_sha256
        != plan["examples_sha256"]
    ):
        raise ValueError("Private style examples changed")
    return plan, inputs


def execute(args: argparse.Namespace) -> dict[str, Any]:
    if not args.owner_approved or not args.approve_plan_sha256:
        raise ValueError(
            "Paid replay needs explicit owner approval and the exact plan SHA256"
        )
    plan, inputs = approved_plan(args.plan, args.approve_plan_sha256)
    output = args.plan.parent / "execution"
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError(
            "OPENAI_API_KEY must be supplied through the existing secret environment"
        )
    # No provider import/client exists before all immutable scope checks succeed.
    from app.services.rag.openai_responses import OpenAIResponsesLLMWrapper
    from openai import OpenAI

    now = datetime.now(timezone.utc)
    trial = ContextTrial.from_settings(
        SimpleNamespace(
            MATRIX_CONTEXT_TRIAL_ID="replay-" + args.approve_plan_sha256[:20],
            MATRIX_CONTEXT_TRIAL_START_AT=(now - timedelta(minutes=1)).isoformat(),
            MATRIX_CONTEXT_TRIAL_END_AT=(
                now + timedelta(seconds=plan["maximum_elapsed_seconds"])
            ).isoformat(),
            MATRIX_CONTEXT_TRIAL_BUDGET_USD=plan["budget_usd"],
            MATRIX_CONTEXT_TRIAL_DAILY_BUDGET_USD=plan["daily_budget_usd"],
            MATRIX_CONTEXT_TRIAL_INPUT_USD_PER_MILLION=plan[
                "input_usd_per_million_ceiling"
            ],
            MATRIX_CONTEXT_TRIAL_OUTPUT_USD_PER_MILLION=plan[
                "output_usd_per_million_ceiling"
            ],
            MATRIX_CONTEXT_SOURCE_ROOMS=["!offline-replay:example.invalid"],
            MATRIX_STAFF_ROOM="!offline-review:example.invalid",
            OPENAI_MODEL=plan["model"],
            MAX_TOKENS=plan["max_output_tokens"],
        )
    )
    output.mkdir(mode=0o700, exist_ok=False)
    write_private(
        output / "execution-intent.json",
        {
            "approved_plan_sha256": args.approve_plan_sha256,
            "started_at": now.isoformat(),
            "no_resume_or_retry": True,
            "trial_descriptor": json.loads(trial.descriptor()),
        },
    )
    input_rate = float(Decimal(plan["input_usd_per_million_ceiling"]) / 1000000)
    output_rate = float(Decimal(plan["output_usd_per_million_ceiling"]) / 1000000)
    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url="https://api.openai.com/v1",
        max_retries=0,
        timeout=90.0,
    )
    llm = OpenAIResponsesLLMWrapper(
        client=client,
        model=plan["model"],
        max_tokens=plan["max_output_tokens"],
        reasoning_effort=plan["reasoning_effort"],
        mcp_url="",
        input_cost_per_token=input_rate,
        cached_input_cost_per_token=input_rate,
        cache_write_cost_per_token=input_rate,
        output_cost_per_token=output_rate,
    )
    try:
        store = ContextTrialStore(str(output / "replay.db"), trial)
        result = asyncio.run(
            replay(plan, inputs, output, ReplayCalls(plan, llm, store, output))
        )
    finally:
        client.close()
    from app.scripts.summarize_staff_context import summarize

    summaries = summarize(output / "replay.db")
    result["model_usage_by_kind"] = next(
        (
            row["model_usage_by_kind"]
            for row in summaries
            if row["trial_id"] == trial.trial_id
        ),
        None,
    )
    write_private(output / "result.json", result)
    report = output / "REPORT.md"
    report.write_text(render_report(result))
    os.chmod(report, 0o600)
    return {
        "result": str(output / "result.json"),
        "status": result["status"],
        "started_calls": result["provider_invocations_started_or_uncertain"],
        "matrix_requests": 0,
        "messages_sent": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser(
        "prepare", help="Offline preparation only; no provider calls"
    )
    for name in ("cases", "threads", "sessions", "comparisons", "data-dir", "output"):
        prep.add_argument("--" + name, type=Path, required=True)
    prep.add_argument("--model", default="openai:gpt-6-astra")
    prep.add_argument(
        "--reasoning-effort", choices=("low", "medium", "high"), default="low"
    )
    prep.add_argument("--max-output-tokens", type=int, default=4000)
    prep.add_argument("--input-usd-per-million", default="12.5")
    prep.add_argument("--output-usd-per-million", default="50")
    prep.add_argument("--budget-usd", required=True)
    prep.add_argument("--daily-budget-usd", required=True)
    prep.add_argument("--max-model-calls", type=int, default=400)
    prep.add_argument("--maximum-elapsed-seconds", type=int, default=7200)
    prep.add_argument("--first-response-delay-seconds", type=float, default=300)
    run = commands.add_parser(
        "execute", help="Paid; requires exact prepared scope and owner approval"
    )
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--approve-plan-sha256")
    run.add_argument("--owner-approved", action="store_true")
    args = parser.parse_args()
    try:
        result = prepare(args) if args.command == "prepare" else execute(args)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

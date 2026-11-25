"""Read-only per-trial Staff-context verdict and routing report.

Run locally against an authorized SQLite copy:
    python -m app.scripts.summarize_staff_context --database /path/escalations.db

Verdicts describe what reviewers would send, not actual reuse or time saved.
No learning, provider, Matrix, or application-runtime imports are performed.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any

VERDICTS = ("would_send_as_is", "would_send_after_edit", "wrong", "not_needed")


def summarize(database: Path) -> list[dict[str, Any]]:
    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        columns = {row[1] for row in db.execute("PRAGMA table_info(escalations)")}
        verdict_column = (
            "staff_context_verdicts"
            if "staff_context_verdicts" in columns
            else "'[]' AS staff_context_verdicts"
        )
        rows = db.execute(
            "SELECT id,channel_metadata,routing_reason,"
            + verdict_column
            + " FROM escalations WHERE channel='matrix' ORDER BY id"
        )
        trials: dict[str, dict[str, Any]] = {}
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='matrix_context_trials' AND type='table'"
        ).fetchone()
        if table:
            for row in db.execute("SELECT trial_id FROM matrix_context_trials"):
                trials[row[0]] = _empty(row[0])
        for row in rows:
            metadata = json.loads(row["channel_metadata"] or "{}")
            if (
                metadata.get("delivery_audience") != "staff_room"
                or metadata.get("response_kind") != "public_context"
            ):
                continue
            trial_id = metadata.get("context_trial_id") or "unbound"
            trial = trials.setdefault(trial_id, _empty(trial_id))
            trial["cases"] += 1
            reason = (
                metadata.get("context_reason") or row["routing_reason"] or "unknown"
            )
            trial["outcome_counts_by_reason"][reason] += 1
            history = [
                entry["event_id"]
                for entry in metadata.get("staff_note_history", [])
                if isinstance(entry, dict)
                and isinstance(entry.get("event_id"), str)
                and entry["event_id"]
            ]
            current = metadata.get("staff_note_event_id")
            diagnostic = metadata.get("staff_note_delivery") or {}
            if (
                isinstance(current, str)
                and current
                and (
                    metadata.get("context_status") == "delivered"
                    or (
                        diagnostic.get("reason_category") == "acknowledged"
                        and diagnostic.get("response_received") is True
                        and diagnostic.get("response_event_id") == current
                    )
                )
            ):
                history.append(current)
            safety_reason = reason == "context_pii_detected" or (
                reason == "invalid_model_output"
                and metadata.get("validation_diagnostic") == "unsafe_reply"
            )
            uncertain = metadata.get("context_status") == "delivery_uncertain" or bool(
                metadata.get("conversation_delivery_uncertain")
            )
            records = json.loads(row["staff_context_verdicts"] or "[]")
            latest_note = history[-1] if history else None
            votes = sorted(
                (
                    r
                    for r in records
                    if latest_note
                    and r.get("target_event_id") == latest_note
                    and r.get("verdict") in VERDICTS
                    and r.get("reviewer")
                ),
                key=lambda r: (r.get("at", ""), r.get("event_id", "")),
            )
            by_reviewer = {r["reviewer"]: r["verdict"] for r in votes}
            drafted = bool(
                history or metadata.get("conversation_last_preview_renderable")
            )
            eligible = bool(latest_note and not safety_reason and not uncertain)
            trial["requests"].append(
                {
                    "request_id": row["id"],
                    "drafted": drafted,
                    "eligible_for_verdict_rate": eligible,
                    "reviewer_verdicts": {
                        f"reviewer-{i}": by_reviewer[name]
                        for i, name in enumerate(sorted(by_reviewer), 1)
                    },
                    "withheld_by_safety_check": safety_reason,
                    "delivery_uncertain": uncertain,
                }
            )
            trial["requests_drafted"] += int(drafted)
            trial["requests_with_safety_withhold"] += int(safety_reason)
            trial["requests_with_delivery_uncertain"] += int(uncertain)
            trial["drafts_eligible_for_verdict"] += int(eligible)
            if eligible and votes:
                trial["drafts_with_verdict"] += 1
                trial["headline_verdict_counts"][votes[-1]["verdict"]] += 1
                for verdict in set(by_reviewer.values()):
                    trial["drafts_with_any_reviewer_verdict"][verdict] += 1
            # Historical per-version coverage is diagnostic, separate from request outcomes.
            versions = trial["version_diagnostics"]
            posted_ids = set(history)
            versions["notes_posted"] += len(posted_ids)
            versions["posted_notes_with_verdict"] += len(
                posted_ids & {record.get("target_event_id") for record in records}
            )
            for record in records:
                if record.get("verdict") in VERDICTS:
                    versions["verdict_counts"][record["verdict"]] += 1
            activity = metadata.get("staff_context_thread_activity") or metadata.get(
                "staff_context_proposed_answer"
            )
            if isinstance(activity, dict) and activity.get("answer"):
                trial["requests_with_thread_activity"] += 1
        spend_table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='matrix_context_trial_spend' AND type='table'"
        ).fetchone()
        if spend_table:
            for receipt in db.execute("SELECT * FROM matrix_context_trial_spend"):
                trial = trials.setdefault(
                    receipt["trial_id"], _empty(receipt["trial_id"])
                )
                kind = receipt["kind"]
                if kind not in {"gate", "note", "update"}:
                    continue
                if trial["model_usage_by_kind"] is None:
                    trial["model_usage_by_kind"] = _empty_model_usage()
                usage = trial["model_usage_by_kind"][kind]
                status = receipt["status"]
                if status == "not_started":
                    usage["cancelled_before_start"] += 1
                    continue
                usage["started_or_uncertain"] += 1
                if status in {"settled", "overrun"}:
                    usage["usage_observed"] += 1
                if status == "uncertain":
                    usage["uncertain"] += 1
                for key in ("input_tokens", "output_tokens"):
                    value = receipt[key]
                    if isinstance(value, int) and value >= 0:
                        usage["observed_" + key] += value
                charged = receipt["actual_nanodollars"]
                if charged is None:
                    charged = receipt["reserved_nanodollars"]
                usage["accounted_nanodollars"] += charged
        result = []
        for trial in trials.values():
            eligible = trial["drafts_eligible_for_verdict"]
            trial["draft_verdict_coverage"] = (
                trial["drafts_with_verdict"] / eligible if eligible else None
            )
            versions = trial["version_diagnostics"]
            versions["share_of_posted_notes_with_verdict"] = (
                versions["posted_notes_with_verdict"] / versions["notes_posted"]
                if versions["notes_posted"]
                else None
            )
            trial["outcome_counts_by_reason"] = dict(
                sorted(trial["outcome_counts_by_reason"].items())
            )
            result.append(trial)
        return sorted(result, key=lambda item: item["trial_id"])


def _empty(trial_id: str) -> dict[str, Any]:
    return {
        "trial_id": trial_id,
        "cases": 0,
        "requests": [],
        "requests_drafted": 0,
        "drafts_eligible_for_verdict": 0,
        "drafts_with_verdict": 0,
        "headline_verdict_counts": dict.fromkeys(VERDICTS, 0),
        "drafts_with_any_reviewer_verdict": dict.fromkeys(VERDICTS, 0),
        "requests_with_thread_activity": 0,
        "requests_with_safety_withhold": 0,
        "requests_with_delivery_uncertain": 0,
        "version_diagnostics": {
            "notes_posted": 0,
            "posted_notes_with_verdict": 0,
            "verdict_counts": dict.fromkeys(VERDICTS, 0),
        },
        "outcome_counts_by_reason": Counter(),
        "model_usage_by_kind": None,
    }


def _empty_model_usage() -> dict[str, dict[str, int]]:
    return {
        kind: {
            "started_or_uncertain": 0,
            "usage_observed": 0,
            "uncertain": 0,
            "cancelled_before_start": 0,
            "observed_input_tokens": 0,
            "observed_output_tokens": 0,
            "accounted_nanodollars": 0,
        }
        for kind in ("gate", "note", "update")
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            {
                "counting": "One row per request. Verdict coverage uses requests with a posted note, excluding current safety withholds and uncertain deliveries. Only each reviewer's latest active reaction on the latest posted version counts. Any-reviewer counts overlap on disagreement. The exclusive headline uses the most recent active verdict, breaking timestamp ties by event ID. Thread activity does not imply an answer was proposed or reused. Version diagnostics are separate from request totals.",
                "model_spend_scope": "Gate, note and update calls only. Accounted nanodollars use approved conservative prices and include uncertain reservations; one USD is 1000000000 nanodollars. Missing token usage is unknown, not zero-cost. Retrieval embeddings and other auxiliary costs are excluded.",
                "trials": summarize(args.database),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

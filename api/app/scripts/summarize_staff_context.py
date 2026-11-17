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
        rows = db.execute(
            "SELECT * FROM escalations WHERE channel='matrix' ORDER BY id"
        ).fetchall()
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
            posted_ids = {
                entry["event_id"]
                for entry in metadata.get("staff_note_history", [])
                if isinstance(entry, dict) and isinstance(entry.get("event_id"), str)
            }
            diagnostic = metadata.get("staff_note_delivery") or {}
            acknowledged = (
                diagnostic.get("reason_category") == "acknowledged"
                and diagnostic.get("response_received") is True
                and diagnostic.get("response_event_id")
                == metadata.get("staff_note_event_id")
                and metadata.get("context_status") != "delivery_uncertain"
            )
            if (
                metadata.get("context_status") == "delivered" or acknowledged
            ) and metadata.get("staff_note_event_id"):
                posted_ids.add(metadata["staff_note_event_id"])
            trial["notes_posted"] += len(posted_ids)
            if metadata.get("context_status") == "delivery_uncertain":
                trial["notes_delivery_uncertain"] += 1
            records = (
                json.loads(row["staff_context_verdicts"] or "[]")
                if "staff_context_verdicts" in row.keys()
                else []
            )
            if records:
                trial["cases_with_verdict"] += 1
                covered = {record.get("target_event_id") for record in records}
                trial["posted_notes_with_verdict"] += len(posted_ids & covered)
                for record in records:
                    verdict = record.get("verdict")
                    if verdict in VERDICTS:
                        trial["verdict_counts"][verdict] += 1
            if row["staff_answer"]:
                trial["cases_with_proposed_staff_answer"] += 1
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
            total = trial["notes_posted"]
            trial["share_of_posted_notes_with_verdict"] = (
                trial["posted_notes_with_verdict"] / total if total else None
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
        "notes_posted": 0,
        "notes_delivery_uncertain": 0,
        "posted_notes_with_verdict": 0,
        "cases_with_verdict": 0,
        "verdict_counts": dict.fromkeys(VERDICTS, 0),
        "cases_with_proposed_staff_answer": 0,
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
                "counting": "Notes posted means a durable delivered outcome with a note event ID. Verdict counts are latest active verdict per reviewer per note; disagreements remain separate. Neither proves actual reuse, delivery verification, or measured quality.",
                "model_spend_scope": "Gate, note and update calls only. Accounted nanodollars use approved conservative prices and include uncertain reservations; one USD is 1000000000 nanodollars. Missing token usage is unknown, not zero-cost. Retrieval embeddings and other auxiliary costs are excluded.",
                "trials": summarize(args.database),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

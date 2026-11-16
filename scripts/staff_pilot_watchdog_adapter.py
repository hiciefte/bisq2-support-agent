#!/usr/bin/env python3
"""Unbound host adapter for the existing frozen trial helper/receipt contracts.

A new reviewed package supplies the descriptor, helpers and source manifest.
This file neither installs nor activates that package. It never edits an old
helper or emits database rows, identities, message text or subprocess stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from staff_pilot_watchdog import PHASES, Refusal, digest, load_binding, need, private

# Existing snapshot failures that prove a material preservation/scope failure,
# unlike an unavailable service/read dependency. The caller still requires the
# returned trial/revision/descriptor to match its independently pinned binding.
MATERIAL_FAILURES = {
    # validate_api / policy_snapshot / cursor_snapshot in the existing watchdog.
    "api_phase_receipt_unverified",
    "api_container_changed",
    "api_environment_changed",
    "api_runtime_unbound",
    "api_build_changed",
    "api_image_changed",
    "forbidden_delivery_flag_enabled",
    "trial_runtime_binding_changed",
    "api_data_mount_changed",
    "matrix_policy_missing",
    "matrix_policy_scope_changed",
    "matrix_generation_flag_invalid",
    "launch_controls_changed",
    "session_path_changed",
    "established_session_changed",
    "established_identity_changed",
    "crypto_database_name_invalid",
    "crypto_database_missing",
    "saved_cursor_or_crypto_account_missing",
    "session_changed_during_observation",
    # Bound scope, receipts, scheduler hold and source/history invariants.
    "descriptor_fields_invalid",
    "descriptor_id_invalid",
    "descriptor_scope_invalid",
    "descriptor_window_invalid",
    "historical_directory_changed",
    "predecessor_closeout_changed",
    "successor_descriptor_changed",
    "summary_helper_hash_changed",
    "admission_cap_exceeded",
    "deployed_revision_changed",
    "phase_descriptor_mismatch",
    "scheduler_hold_receipt_invalid",
    "scheduler_command_changed",
    "scheduler_overlay_changed",
    "baseline_readiness_invalid",
    "baseline_receipt_changed",
    "duplicate_project_service",
    "held_history_policy_changed",
    "trial_descriptor_mismatch",
    "trial_case_source_mismatch",
    "trial_case_destination_mismatch",
    # Exact held_history guard codes: preserve history failure independently of
    # generic unavailable Docker/SQLite/service reads, which remain unclassified.
    "active_or_unclassified_context_attempt",
    "active_or_unknown_model_attempt",
    "closed_attempt_rows_changed",
    "closed_case_rows_changed",
    "closed_history_changed",
    "closed_trial_not_expired",
    "completed_model_without_reservation",
    "cross_trial_reservation",
    "duplicate_attempt",
    "held_attempt_changed",
    "held_attempt_missing_or_reclassified",
    "held_attempt_not_terminal",
    "held_disposition_unbound",
    "held_inventory_count",
    "held_inventory_not_exact",
    "held_pin_unbound",
    "history_count_invalid",
    "history_descriptor_count",
    "history_descriptor_id_mismatch",
    "history_inventory_changed",
    "history_inventory_unbound",
    "history_pin_unbound",
    "history_policy_not_reviewed",
    "history_policy_schema",
    "history_table_shape",
    "orphan_context_attempt",
    "orphan_or_wrong_trial_reservation",
    "successor_id_unbound",
    "successor_work_before_activation",
    "unclassified_model_attempt",
    "unreviewed_delivery_uncertainty",
    "unscoped_context_case",
}


def load_config(path, expected):
    raw = private(path)
    need(digest(raw) == expected, "adapter_config_changed")
    c = json.loads(raw)
    need(
        set(c)
        == {
            "schema",
            "binding_path",
            "descriptor_path",
            "database_path",
            "health_command",
            "phase_commands",
            "files_sha256",
        }
        and c["schema"] == "staff-pilot-watchdog-adapter-v1",
        "adapter_config_fields",
    )
    for key in ("binding_path", "descriptor_path", "database_path"):
        need(Path(c[key]).is_absolute(), "adapter_path_invalid")
    # No circular hash: the coordinator pins this config; this config names its
    # coordinator binding, whose hash is supplied by the same reviewed command.
    for path, expected_sha in c["files_sha256"].items():
        need(
            Path(path).is_absolute() and digest(private(Path(path))) == expected_sha,
            "adapter_source_changed",
        )
    need(set(c["phase_commands"]) == set(PHASES), "adapter_phase_commands")
    for cmd in [c["health_command"], *c["phase_commands"].values()]:
        need(
            isinstance(cmd, list)
            and len(cmd) >= 2
            and cmd[0] in ("/usr/bin/python3", "/bin/bash")
            and all(isinstance(s, str) and "\x00" not in s for s in cmd)
            and any(arg in c["files_sha256"] for arg in cmd[1:]),
            "adapter_command_unpinned",
        )
    return c


def limits(config, binding, now=None):
    """Read only counts and fixed status fields from the existing durable ledger.

    Source rooms and all raw descriptor/database values remain host-local.
    Missing descriptor + zero reservations is the normal initial state.
    """
    raw = private(Path(config["descriptor_path"]))
    need(digest(raw) == binding["descriptor_sha256"], "limits_descriptor_changed")
    descriptor = json.loads(raw)
    for key in ("trial_id", "start_at", "end_at", "max_cases"):
        need(descriptor[key] == binding[key], "limits_descriptor_changed")
    path = Path(config["database_path"])
    need(
        path.is_file() and not path.is_symlink() and path.resolve(strict=True) == path,
        "limits_database_unavailable",
    )
    with closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    ) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        tables = {
            r[0]
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        need("escalations" in tables, "limits_schema_unavailable")
        row = None
        if "matrix_context_trials" in tables:
            row = db.execute(
                "SELECT descriptor FROM matrix_context_trials WHERE trial_id=?",
                (binding["trial_id"],),
            ).fetchone()
        reserved, active = 0, 0
        if "matrix_context_trial_cases" in tables:
            reserved = db.execute(
                "SELECT COUNT(*) FROM matrix_context_trial_cases WHERE trial_id=?",
                (binding["trial_id"],),
            ).fetchone()[0]
            # No content column leaves SQLite. Missing reserved cases count as
            # uncertain; reservation consumption survives case retention.
            active = db.execute(
                """SELECT COUNT(*) FROM matrix_context_trial_cases r
                LEFT JOIN escalations e ON e.id=r.escalation_id
                WHERE r.trial_id=? AND CASE
                    WHEN e.id IS NULL OR json_valid(e.channel_metadata) IS NOT 1 THEN 1
                    WHEN json_type(e.channel_metadata, '$.context_status') IS NOT 'text'
                      OR json_type(e.channel_metadata, '$.model_call_status') IS NOT 'text' THEN 1
                    WHEN json_extract(e.channel_metadata, '$.context_status') IN
                       ('preparing','delivery_pending','delivery_uncertain')
                      OR json_extract(e.channel_metadata, '$.model_call_status') IN
                       ('reserved','outcome_unknown') THEN 1 ELSE 0 END""",
                (binding["trial_id"],),
            ).fetchone()[0]
        need(row is not None or reserved == 0, "limits_orphan_reservations")
        need(
            row is None or json.loads(row[0]) == descriptor, "limits_descriptor_changed"
        )
        db.rollback()
    return {
        "trial_id": binding["trial_id"],
        "revision": binding["revision"],
        "descriptor_sha256": binding["descriptor_sha256"],
        "captured_at": (now or datetime.now(timezone.utc)).isoformat(),
        "reserved_cases": reserved,
        "max_cases": binding["max_cases"],
        "uncertain_or_active_count": active,
        "matrix_requests": 0,
        "provider_calls": 0,
    }


def execute(config, binding, kind, *, checkpoint=None, run=subprocess.run):
    if kind == "limits":
        return limits(config, binding)
    if kind == "health":
        cmd = [*config["health_command"]]
        if checkpoint is not None:
            need(
                checkpoint == Path(binding["state_dir"]) / "checkpoint.json",
                "adapter_checkpoint_changed",
            )
            cmd += ["--checkpoint", str(checkpoint)]
    else:
        need(kind in PHASES, "adapter_phase_invalid")
        cmd = config["phase_commands"][kind]
        need(
            len(cmd) == 5
            and cmd[0] == "/bin/bash"
            and cmd[2:] == [kind, binding["descriptor_sha256"], "none"],
            "canonical_control_wrapper_required",
        )
    result = run(cmd, capture_output=True, timeout=140 if kind == "health" else 890)
    need(result.returncode == 0, "adapter_command_failed")
    if kind in PHASES:
        # Original canonical intent/receipt files are already in the coordinator
        # contract. Never duplicate, normalize, overwrite or invent receipts.
        return {"controller_returned": True, "success_requires_canonical_receipt": True}
    need(len(result.stdout) < 40000, "adapter_health_too_large")
    value = json.loads(result.stdout)
    need(isinstance(value, dict), "adapter_health_invalid")
    if value.get("failure_code") in MATERIAL_FAILURES or (
        value.get("failure_code") == "watchdog_read_dependency_unavailable"
        and value.get("error_type") in {"HeldHistoryError", "BindingError"}
    ):
        # The preserved older snapshot catches these typed guard refusals as a
        # generic dependency error. The fixed type still distinguishes them
        # from unavailable filesystem/SQLite/Docker reads; do not invent a code.
        value["material_safety_failure"] = True
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument(
        "--binding-sha256", default=os.environ.get("STAFF_PILOT_BINDING_SHA256")
    )
    parser.add_argument("kind", choices=["limits", "health", *PHASES])
    parser.add_argument("--checkpoint", type=Path)
    args = parser.parse_args()
    try:
        need(os.geteuid() == 0 and __debug__, "root_nonoptimized_execution_required")
        config = load_config(args.config, args.config_sha256)
        binding = load_binding(Path(config["binding_path"]), args.binding_sha256)
        # Both manifests must protect every adapter dependency, including config.
        for path, expected in config["files_sha256"].items():
            need(
                binding["files_sha256"].get(path) == expected,
                "adapter_manifest_mismatch",
            )
        need(
            binding["files_sha256"].get(str(args.config)) == args.config_sha256,
            "adapter_config_not_bound",
        )
        print(
            json.dumps(execute(config, binding, args.kind, checkpoint=args.checkpoint))
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "error_code": (
                        str(exc) if isinstance(exc, Refusal) else "adapter_read_failed"
                    ),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

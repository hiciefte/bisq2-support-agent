"""Shared data contracts for the ordinary selective deployment controller.

Validation neither grants authority nor runs effects. Profiles contain protected
references, never command hooks or secret values. Receipts are success evidence;
private diagnostics and failed/uncertain outcomes belong to the effect journal.
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import cast
from urllib.parse import urlsplit

from lib.deployment_journal import JournalError, digest, now, require, timestamp

MAX_RECORD_BYTES = 64 * 1024
SLUG = r"[a-z][a-z0-9_-]{0,63}"
COMMIT = r"[0-9a-f]{40}"
SHA256 = r"[0-9a-f]{64}"
IMAGE = r"sha256:[0-9a-f]{64}"
# These sets are the actual public helpers consumed by the fixed backends.
HOST_HELPERS = frozenset(
    {
        "scripts/deploy_release_host.py",
        "scripts/deploy_release.py",
        "scripts/lib/deployment_protocol.py",
        "scripts/lib/deployment_host.py",
        "scripts/lib/deployment_host.sh",
        "scripts/lib/deployment_recovery.py",
        "scripts/lib/common.sh",
        "scripts/lib/docker-utils.sh",
        "scripts/lib/git-utils.sh",
        "scripts/lib/docker_identity.py",
        "scripts/lib/lifecycle_lock.py",
        "scripts/lib/deployment_journal.py",
        "scripts/verify-release-ai-quality-gate.sh",
    }
)
VERIFIER_HELPERS = frozenset(
    {
        "scripts/backup.sh",
        "scripts/restore.sh",
        "scripts/lib/common.sh",
        "scripts/lib/lifecycle_lock.py",
        "scripts/lib/docker_identity.py",
        "api/app/scripts/disaster_recovery.py",
    }
)


def _match(value: object, pattern: str) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(pattern, value))


def _keys(value: object, keys: set[str], code: str) -> dict:
    require(isinstance(value, dict) and set(value) == keys, code)
    return cast(dict, value)


def _path(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 < len(value) <= 4096
        and value.startswith("/")
        and not value.startswith("//")
        and str(PurePosixPath(value)) == value
        and not any(part in {".", ".."} for part in value.split("/"))
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


def _integer(value: object, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _build_id(value: object, plan: dict) -> bool:
    return (
        isinstance(value, str)
        and _match(value, r"build-[0-9a-f]{7,40}")
        and plan["source"]["candidate_commit"].startswith(value.removeprefix("build-"))
    )


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "protocol_json")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise JournalError("protocol_json")


def decode_object(raw: bytes) -> dict:
    require(isinstance(raw, bytes) and len(raw) <= MAX_RECORD_BYTES, "protocol_json")
    try:
        result = json.loads(
            raw, object_pairs_hook=_pairs, parse_constant=_invalid_constant
        )
        require(isinstance(result, dict), "protocol_json")
        return result
    except (ValueError, TypeError, RecursionError) as error:
        raise JournalError("protocol_json") from error


def encode_object(record: dict) -> bytes:
    require(isinstance(record, dict), "protocol_json")
    try:
        raw = (
            json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n"
        ).encode()
    except (ValueError, TypeError, RecursionError) as error:
        raise JournalError("protocol_json") from error
    require(len(raw) <= MAX_RECORD_BYTES, "protocol_json")
    return raw


def canonical_sha256(record: dict) -> str:
    return digest(encode_object(record))


def phases_for(services: list[str], *, publish_source: bool = True) -> list[str]:
    phases = ["build", "pause_scheduler", "prechange_backup", "prechange_restore"]
    phases.extend("switch_" + service for service in services)
    if "api" in services:
        phases.extend(["smoke_standard", "smoke_live_mcp"])
    phases.extend(["postchange_backup", "postchange_restore"])
    if publish_source:
        phases.append("publish_source")
    return phases + ["resume_scheduler"]


def validate_plan(plan: dict) -> None:
    _keys(
        plan,
        {
            "schema",
            "kind",
            "created_at",
            "deadline",
            "profile",
            "source",
            "services",
            "phases",
        },
        "release_plan_schema",
    )
    require(
        plan["schema"] in ["deployment-plan-v1", "deployment-plan-v2"]
        and plan["kind"] == "selective-api-web-v1",
        "release_plan_schema",
    )
    require(
        timestamp(plan["created_at"]) < timestamp(plan["deadline"]), "release_window"
    )
    require(_match(plan["profile"], SLUG), "profile_reference")
    require(plan["services"] in [["api"], ["web"], ["api", "web"]], "release_services")
    require(
        plan["phases"]
        == phases_for(
            plan["services"], publish_source=plan["schema"] == "deployment-plan-v2"
        ),
        "release_phases",
    )
    source = _keys(
        plan["source"],
        {
            "candidate_commit",
            "candidate_tree",
            "previous_commit",
            "previous_tree",
            "changed_paths_sha256",
        },
        "release_source",
    )
    require(
        all(
            _match(source[key], COMMIT)
            for key in source
            if key != "changed_paths_sha256"
        )
        and source["candidate_commit"] != source["previous_commit"]
        and _match(source["changed_paths_sha256"], SHA256),
        "release_source",
    )


def _pins(value: object, helpers: frozenset[str]) -> None:
    require(
        bool(helpers)
        and isinstance(value, dict)
        and set(value) == helpers
        and all(_match(pin, SHA256) for pin in value.values()),
        "profile_helper_pins",
    )


def validate_profile(profile: dict) -> None:
    _keys(
        profile,
        {
            "schema",
            "name",
            "transport",
            "host",
            "recovery",
            "phase_timeout_seconds",
            "helper_sha256",
        },
        "profile_schema",
    )
    require(
        profile["schema"] == "deployment-profile-v1" and _match(profile["name"], SLUG),
        "profile_schema",
    )
    transport = _keys(
        profile["transport"], {"kind", "ssh_alias", "host_python"}, "profile_transport"
    )
    require(
        (transport["kind"] == "ssh" and _match(transport["ssh_alias"], SLUG))
        or (transport["kind"] == "local_rehearsal" and transport["ssh_alias"] is None),
        "profile_transport",
    )
    require(_path(transport["host_python"]), "profile_path")
    host = _keys(
        profile["host"],
        {
            "repository",
            "candidate",
            "operation_root",
            "compose_project",
            "compose_file",
            "quality_remote",
            "readiness_timeout_seconds",
            "nginx_url",
        },
        "profile_host",
    )
    require(
        all(_path(host[key]) for key in ("repository", "candidate", "operation_root")),
        "profile_path",
    )
    require(host["repository"] != host["candidate"], "profile_source_paths")
    require(
        _match(host["compose_project"], SLUG) and _match(host["quality_remote"], SLUG),
        "profile_host",
    )
    require(
        host["compose_file"] == "docker-compose.yml"
        and _integer(host["readiness_timeout_seconds"], 30, 300),
        "profile_host",
    )
    try:
        require(
            _match(
                host["nginx_url"],
                r"http://(?:127\.0\.0\.1|localhost|\[::1\])(?::[0-9]{1,5})?/?",
            ),
            "profile_nginx_url",
        )
        url = urlsplit(host["nginx_url"])
        require(
            isinstance(host["nginx_url"], str)
            and url.scheme == "http"
            and url.hostname in {"127.0.0.1", "localhost", "::1"}
            and url.username is None
            and url.password is None
            and url.path in {"", "/"}
            and not url.query
            and not url.fragment
            and (url.port is None or 1 <= url.port <= 65535),
            "profile_nginx_url",
        )
    except (ValueError, TypeError, AttributeError) as error:
        raise JournalError("profile_nginx_url") from error
    require(_integer(profile["phase_timeout_seconds"], 30, 1800), "profile_timeout")
    _pins(profile["helper_sha256"], HOST_HELPERS)
    _validate_recovery(profile["recovery"])


def _validate_recovery(recovery: dict) -> None:
    _keys(
        recovery,
        {
            "export_directory",
            "encryption",
            "recipient_file",
            "local_directory",
            "verifier_repository",
            "verifier_runtime",
            "identity_file",
            "expected_helper_sha256",
        },
        "profile_recovery",
    )
    require(
        all(
            _path(recovery[key])
            for key in (
                "export_directory",
                "recipient_file",
                "local_directory",
                "verifier_repository",
                "identity_file",
            )
        ),
        "profile_path",
    )
    require(recovery["encryption"] in ["age", "gpg"], "profile_encryption")
    _pins(recovery["expected_helper_sha256"], VERIFIER_HELPERS)
    runtime = _keys(
        recovery["verifier_runtime"],
        {
            "docker_executable",
            "docker_executable_sha256",
            "docker_socket",
            "runtime_image_id",
            "api_image_id",
            "qdrant_image_id",
            "uid",
            "gid",
        },
        "profile_verifier_runtime",
    )
    require(
        _path(runtime["docker_executable"])
        and _path(runtime["docker_socket"])
        and _match(runtime["docker_executable_sha256"], SHA256),
        "profile_verifier_runtime",
    )
    require(
        all(
            _match(runtime[key], IMAGE)
            for key in ("runtime_image_id", "api_image_id", "qdrant_image_id")
        )
        and _integer(runtime["uid"], 0, 2**31 - 1)
        and _integer(runtime["gid"], 0, 2**31 - 1),
        "profile_verifier_runtime",
    )


def validate_approval(approval: dict, plan: dict, profile: dict) -> None:
    validate_plan(plan)
    validate_profile(profile)
    _keys(
        approval,
        {
            "schema",
            "plan_sha256",
            "profile_sha256",
            "phases",
            "operator",
            "approved_at",
            "deadline",
            "smoke_calls",
            "image_consumers",
            "data_compatible_rollback",
            "policy",
        },
        "approval_schema",
    )
    require(
        approval["schema"] == "deployment-approval-v2"
        and approval["plan_sha256"] == canonical_sha256(plan)
        and approval["profile_sha256"] == canonical_sha256(profile)
        and profile["name"] == plan["profile"],
        "approval_binding",
    )
    require(
        isinstance(approval["operator"], str)
        and 0 < len(approval["operator"].strip()) <= 128
        and not any(
            ord(char) < 32 or ord(char) == 127 for char in approval["operator"]
        ),
        "approval_operator",
    )
    require(
        timestamp(plan["created_at"])
        <= timestamp(approval["approved_at"])
        < timestamp(approval["deadline"])
        <= timestamp(plan["deadline"]),
        "approval_window",
    )
    require(
        approval["phases"] == plan["phases"]
        and approval["smoke_calls"]
        == (["standard", "live_mcp"] if "api" in plan["services"] else [])
        and approval["data_compatible_rollback"] is True
        and approval["policy"] == "private-disabled-channels",
        "approval_scope",
    )

    consumers = _keys(
        approval["image_consumers"], set(plan["services"]), "approval_consumers"
    )
    for service, physical in consumers.items():
        require(
            physical
            in (
                [["api"], ["api", "matrix-alert-relay"]]
                if service == "api"
                else [["web"]]
            ),
            "approval_consumers",
        )


def validate_image_consumer_scope(payload: dict, approval: dict) -> None:
    """Bind a structurally validated switch proof to its explicit approval."""
    require(
        set(payload["consumers"])
        == set(approval["image_consumers"][payload["service"]]),
        "receipt_consumer_scope",
    )


def effect_guard(
    plan: dict,
    profile: dict,
    approval: dict,
    phase: str,
    current_time: str | None = None,
) -> float:
    """Recheck the immutable binding and time window immediately before an effect."""
    validate_approval(approval, plan, profile)
    require(plan["schema"] == "deployment-plan-v2", "effect_plan_version")
    require(phase in plan["phases"], "unknown_phase")
    instant = timestamp(current_time or now())
    require(
        timestamp(approval["approved_at"]) <= instant < timestamp(approval["deadline"]),
        "effect_deadline",
    )
    return min(
        float(profile["phase_timeout_seconds"]),
        (timestamp(approval["deadline"]) - instant).total_seconds(),
    )


def _validate_payload(phase: str, payload: dict, plan: dict) -> None:
    if phase == "build":
        _keys(
            payload,
            {"images", "quality_verified", "unrelated_preserved"},
            "receipt_payload",
        )
        images = _keys(payload["images"], set(plan["services"]), "receipt_images")
        for image in images.values():
            _keys(
                image,
                {"image_id", "image_inspect_sha256", "build_id"},
                "receipt_images",
            )
            require(
                _match(image["image_id"], IMAGE)
                and _match(image["image_inspect_sha256"], SHA256),
                "receipt_images",
            )
            require(_build_id(image["build_id"], plan), "receipt_build_id")
        flags = ["quality_verified", "unrelated_preserved"]
    elif phase == "pause_scheduler":
        _keys(
            payload,
            {"scheduler_id", "paused_by_session", "prior_paused", "identity_sha256"},
            "receipt_payload",
        )
        require(
            _match(payload["scheduler_id"], SHA256)
            and _match(payload["identity_sha256"], SHA256),
            "receipt_identity",
        )
        require(
            type(payload["paused_by_session"]) is bool
            and type(payload["prior_paused"]) is bool
            and payload["paused_by_session"] != payload["prior_paused"],
            "receipt_pause_owner",
        )
        flags = []
    elif phase in {"switch_api", "switch_web"}:
        _keys(
            payload,
            {
                "service",
                "consumers",
                "container_id",
                "image_id",
                "build_id",
                "ready",
                "nginx_routing_verified",
                "unrelated_preserved",
            },
            "receipt_payload",
        )
        require(
            payload["service"] == phase.removeprefix("switch_")
            and _match(payload["container_id"], SHA256)
            and _match(payload["image_id"], IMAGE),
            "receipt_identity",
        )
        require(_build_id(payload["build_id"], plan), "receipt_build_id")
        consumers = payload["consumers"]
        require(
            isinstance(consumers, dict)
            and set(consumers)
            in (
                [{"api"}, {"api", "matrix-alert-relay"}]
                if payload["service"] == "api"
                else [{"web"}]
            ),
            "receipt_consumers",
        )
        for proof in consumers.values():
            _keys(proof, {"container_id", "image_id", "ready"}, "receipt_consumers")
            require(
                _match(proof["container_id"], SHA256)
                and proof["image_id"] == payload["image_id"]
                and proof["ready"] is True,
                "receipt_consumers",
            )
        require(
            len({item["container_id"] for item in consumers.values()}) == len(consumers)
            and consumers[payload["service"]]["container_id"]
            == payload["container_id"],
            "receipt_consumers",
        )
        flags = ["ready", "nginx_routing_verified", "unrelated_preserved"]
    elif phase in {"smoke_standard", "smoke_live_mcp"}:
        _keys(payload, {"kind", "validated", "attempts"}, "receipt_payload")
        require(
            payload["kind"] == phase.removeprefix("smoke_")
            and type(payload["attempts"]) is int
            and payload["attempts"] == 1,
            "receipt_smoke",
        )
        flags = ["validated"]
    elif phase == "resume_scheduler":
        _keys(
            payload,
            {
                "scheduler_id",
                "original_process_preserved",
                "original_pause_restored",
                "job_config_preserved",
                "unrelated_preserved",
            },
            "receipt_payload",
        )
        require(_match(payload["scheduler_id"], SHA256), "receipt_identity")
        flags = [
            "original_process_preserved",
            "original_pause_restored",
            "job_config_preserved",
            "unrelated_preserved",
        ]
    elif phase == "publish_source":
        _keys(
            payload,
            {
                "candidate_commit",
                "candidate_tree",
                "previous_commit",
                "source_clean",
                "unrelated_preserved",
            },
            "receipt_payload",
        )
        require(
            all(
                payload[key] == plan["source"][key]
                for key in ("candidate_commit", "candidate_tree", "previous_commit")
            ),
            "receipt_source",
        )
        flags = ["source_clean", "unrelated_preserved"]
    elif phase in {"prechange_backup", "postchange_backup"}:
        _keys(
            payload,
            {
                "ciphertext_name",
                "ciphertext_sha256",
                "ciphertext_bytes",
                "canonical_backup_receipt_sha256",
                "destination_kind",
                "writers_resumed",
            },
            "receipt_payload",
        )
        require(
            _match(
                payload["ciphertext_name"],
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\.(?:age|gpg)",
            )
            and ".." not in payload["ciphertext_name"],
            "receipt_ciphertext",
        )
        require(
            _match(payload["ciphertext_sha256"], SHA256)
            and _integer(payload["ciphertext_bytes"], 1, 2**63 - 1)
            and _match(payload["canonical_backup_receipt_sha256"], SHA256)
            and payload["destination_kind"] == "same_host_encrypted_export",
            "receipt_ciphertext",
        )
        flags = ["writers_resumed"]
    elif phase in {"prechange_restore", "postchange_restore"}:
        _keys(
            payload,
            {
                "receive_receipt_sha256",
                "ciphertext_sha256",
                "ciphertext_bytes",
                "canonical_restore_receipt_sha256",
                "components",
                "qdrant_restored",
                "scratch_cleanup_verified",
                "local_runtime_image_id",
            },
            "receipt_payload",
        )
        require(
            all(
                _match(payload[key], SHA256)
                for key in (
                    "receive_receipt_sha256",
                    "ciphertext_sha256",
                    "canonical_restore_receipt_sha256",
                )
            )
            and _integer(payload["ciphertext_bytes"], 1, 2**63 - 1)
            and payload["components"] == ["all"]
            and _match(payload["local_runtime_image_id"], IMAGE),
            "receipt_restore",
        )
        flags = ["qdrant_restored", "scratch_cleanup_verified"]
    else:
        raise JournalError("unknown_phase")
    require(all(payload[key] is True for key in flags), "receipt_verification_failed")


def make_phase_receipt(
    plan: dict,
    profile: dict,
    phase: str,
    intent_sha256: str,
    baseline_sha256: str,
    payload: dict,
    started_at: str,
    finished_at: str | None = None,
) -> dict:
    receipt = {
        "schema": "deployment-phase-receipt-v1",
        "plan_sha256": canonical_sha256(plan),
        "profile_sha256": canonical_sha256(profile),
        "phase": phase,
        "intent_sha256": intent_sha256,
        "baseline_sha256": baseline_sha256,
        "started_at": started_at,
        "finished_at": finished_at or now(),
        "payload": payload,
    }
    validate_phase_receipt(
        receipt, plan, profile, phase, intent_sha256, baseline_sha256
    )
    return receipt


def validate_phase_receipt(
    receipt: dict,
    plan: dict,
    profile: dict,
    phase: str,
    intent_sha256: str,
    baseline_sha256: str | None = None,
    *,
    approval: dict | None = None,
) -> dict:
    validate_plan(plan)
    validate_profile(profile)
    _keys(
        receipt,
        {
            "schema",
            "plan_sha256",
            "profile_sha256",
            "phase",
            "intent_sha256",
            "baseline_sha256",
            "started_at",
            "finished_at",
            "payload",
        },
        "receipt_schema",
    )
    require(
        receipt["schema"] == "deployment-phase-receipt-v1"
        and receipt["plan_sha256"] == canonical_sha256(plan)
        and receipt["profile_sha256"] == canonical_sha256(profile)
        and phase in plan["phases"]
        and receipt["phase"] == phase
        and _match(intent_sha256, SHA256)
        and receipt["intent_sha256"] == intent_sha256
        and _match(receipt["baseline_sha256"], SHA256)
        and (baseline_sha256 is None or receipt["baseline_sha256"] == baseline_sha256),
        "receipt_binding",
    )
    require(
        timestamp(plan["created_at"])
        <= timestamp(receipt["started_at"])
        < timestamp(plan["deadline"])
        and timestamp(receipt["started_at"]) <= timestamp(receipt["finished_at"]),
        "receipt_timestamp",
    )
    _validate_payload(phase, receipt["payload"], plan)
    if approval is not None and phase.startswith("switch_"):
        validate_approval(approval, plan, profile)
        validate_image_consumer_scope(receipt["payload"], approval)
    if phase in {"prechange_restore", "postchange_restore"}:
        require(
            receipt["payload"]["local_runtime_image_id"]
            == profile["recovery"]["verifier_runtime"]["runtime_image_id"],
            "receipt_restore_runtime",
        )
    if phase in {"prechange_backup", "postchange_backup"}:
        require(
            receipt["payload"]["ciphertext_name"].endswith(
                "." + profile["recovery"]["encryption"]
            ),
            "receipt_ciphertext",
        )
    return receipt["payload"]


def make_receive_receipt(export_receipt: dict) -> dict:
    """Expected copy proof; publish it only after a verified atomic receive."""
    _keys(
        export_receipt,
        {
            "schema",
            "plan_sha256",
            "profile_sha256",
            "phase",
            "intent_sha256",
            "baseline_sha256",
            "started_at",
            "finished_at",
            "payload",
        },
        "receive_export_schema",
    )
    require(
        export_receipt["schema"] == "deployment-phase-receipt-v1"
        and export_receipt["phase"] in {"prechange_backup", "postchange_backup"}
        and all(
            _match(export_receipt[key], SHA256)
            for key in (
                "plan_sha256",
                "profile_sha256",
                "intent_sha256",
                "baseline_sha256",
            )
        ),
        "receive_export_binding",
    )
    require(
        timestamp(export_receipt["started_at"])
        <= timestamp(export_receipt["finished_at"]),
        "receive_export_timestamp",
    )
    payload = export_receipt["payload"]
    _validate_payload(export_receipt["phase"], payload, {})
    return {
        "schema": "deployment-receive-receipt-v1",
        "export_receipt_sha256": canonical_sha256(export_receipt),
        "ciphertext_sha256": payload["ciphertext_sha256"],
        "ciphertext_bytes": payload["ciphertext_bytes"],
        "atomic_private_copy": True,
    }


def validate_receive_receipt(receipt: dict, export_receipt: dict) -> None:
    require(receipt == make_receive_receipt(export_receipt), "receive_receipt_binding")

"""Synthetic producer/consumer protocol checks; no Docker, SSH or provider calls."""

import copy
import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def protocol(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return importlib.import_module("lib.deployment_protocol")


@pytest.fixture
def records(protocol):
    plan = {
        "schema": "deployment-plan-v2",
        "kind": "selective-api-web-v1",
        "created_at": "2026-01-01T10:00:00+00:00",
        "deadline": "2026-01-01T12:00:00+00:00",
        "profile": "fixture",
        "source": {
            "candidate_commit": "a" * 40,
            "candidate_tree": "b" * 40,
            "previous_commit": "c" * 40,
            "previous_tree": "d" * 40,
            "changed_paths_sha256": "e" * 64,
        },
        "services": ["api", "web"],
        "phases": protocol.phases_for(["api", "web"]),
    }
    profile = {
        "schema": "deployment-profile-v1",
        "name": "fixture",
        "transport": {
            "kind": "local_rehearsal",
            "ssh_alias": None,
            "host_python": "/usr/bin/python3",
        },
        "host": {
            "repository": "/srv/fixture/application",
            "candidate": "/srv/fixture/candidate",
            "operation_root": "/srv/fixture/operations",
            "compose_project": "fixture",
            "compose_file": "docker-compose.yml",
            "quality_remote": "origin",
            "readiness_timeout_seconds": 60,
            "nginx_url": "http://127.0.0.1:8000",
        },
        "phase_timeout_seconds": 300,
        "helper_sha256": {name: "1" * 64 for name in protocol.HOST_HELPERS},
        "recovery": {
            "export_directory": "/srv/fixture/ciphertext",
            "encryption": "age",
            "recipient_file": "/etc/fixture/public-recipient",
            "local_directory": "/private/fixture/recovery",
            "verifier_repository": "/private/fixture/tools",
            "identity_file": "/private/fixture/identity-reference",
            "expected_helper_sha256": {
                name: "2" * 64 for name in protocol.VERIFIER_HELPERS
            },
            "verifier_runtime": {
                "docker_executable": "/usr/local/bin/docker",
                "docker_executable_sha256": "3" * 64,
                "docker_socket": "/private/fixture/docker.sock",
                "runtime_image_id": "sha256:" + "4" * 64,
                "api_image_id": "sha256:" + "5" * 64,
                "qdrant_image_id": "sha256:" + "6" * 64,
                "uid": 501,
                "gid": 20,
            },
        },
    }
    approval = {
        "schema": "deployment-approval-v2",
        "plan_sha256": protocol.canonical_sha256(plan),
        "profile_sha256": protocol.canonical_sha256(profile),
        "phases": plan["phases"],
        "operator": "Synthetic fixture operator",
        "approved_at": "2026-01-01T10:01:00+00:00",
        "deadline": "2026-01-01T11:00:00+00:00",
        "smoke_calls": ["standard", "live_mcp"],
        "image_consumers": {"api": ["api"], "web": ["web"]},
        "data_compatible_rollback": True,
        "policy": "private-disabled-channels",
    }
    return plan, profile, approval


def payload_for(phase):
    if phase == "build":
        return {
            "images": {
                service: {
                    "image_id": "sha256:" + digit * 64,
                    "image_inspect_sha256": "7" * 64,
                    "build_id": "build-aaaaaaa",
                }
                for service, digit in [("api", "8"), ("web", "9")]
            },
            "quality_verified": True,
            "unrelated_preserved": True,
        }
    if phase == "pause_scheduler":
        return {
            "scheduler_id": "0" * 64,
            "paused_by_session": True,
            "prior_paused": False,
            "identity_sha256": "1" * 64,
        }
    if phase.startswith("switch_"):
        return {
            "service": phase.removeprefix("switch_"),
            "consumers": {
                phase.removeprefix("switch_"): {
                    "container_id": "2" * 64,
                    "image_id": "sha256:" + "3" * 64,
                    "ready": True,
                }
            },
            "container_id": "2" * 64,
            "image_id": "sha256:" + "3" * 64,
            "build_id": "build-aaaaaaa",
            "ready": True,
            "nginx_routing_verified": True,
            "unrelated_preserved": True,
        }
    if phase.startswith("smoke_"):
        return {"kind": phase.removeprefix("smoke_"), "validated": True, "attempts": 1}
    if phase.endswith("_backup"):
        return {
            "ciphertext_name": "fixture-backup.tar.gz.age",
            "ciphertext_sha256": "4" * 64,
            "ciphertext_bytes": 2048,
            "canonical_backup_receipt_sha256": "5" * 64,
            "destination_kind": "same_host_encrypted_export",
            "writers_resumed": True,
        }
    if phase.endswith("_restore"):
        return {
            "receive_receipt_sha256": "6" * 64,
            "ciphertext_sha256": "4" * 64,
            "ciphertext_bytes": 2048,
            "canonical_restore_receipt_sha256": "7" * 64,
            "components": ["all"],
            "qdrant_restored": True,
            "scratch_cleanup_verified": True,
            "local_runtime_image_id": "sha256:" + "4" * 64,
        }
    if phase == "publish_source":
        return {
            "candidate_commit": "a" * 40,
            "candidate_tree": "b" * 40,
            "previous_commit": "c" * 40,
            "source_clean": True,
            "unrelated_preserved": True,
        }
    assert phase == "resume_scheduler"
    return {
        "scheduler_id": "0" * 64,
        "original_process_preserved": True,
        "original_pause_restored": True,
        "job_config_preserved": True,
        "unrelated_preserved": True,
    }


def receipt(protocol, plan, profile, phase):
    return protocol.make_phase_receipt(
        plan,
        profile,
        phase,
        "a" * 64,
        "b" * 64,
        payload_for(phase),
        "2026-01-01T10:02:00+00:00",
        "2026-01-01T10:02:10+00:00",
    )


def test_exact_producer_wire_consumer_receipts_for_complete_release(protocol, records):
    plan, profile, approval = records
    for phase in plan["phases"]:
        assert (
            protocol.effect_guard(
                plan, profile, approval, phase, "2026-01-01T10:02:00+00:00"
            )
            == 300
        )
        produced = receipt(protocol, plan, profile, phase)
        wire = protocol.encode_object(produced)
        consumed = protocol.decode_object(wire)
        assert protocol.validate_phase_receipt(
            consumed, plan, profile, phase, "a" * 64, "b" * 64
        ) == payload_for(phase)
        assert protocol.canonical_sha256(produced) == protocol.canonical_sha256(
            consumed
        )


@pytest.mark.parametrize(
    "phase", ["build", "switch_api", "prechange_backup", "smoke_standard"]
)
def test_every_effect_refuses_exact_deadline_even_after_prior_success(
    protocol, records, phase
):
    plan, profile, approval = records
    assert (
        protocol.effect_guard(
            plan, profile, approval, phase, "2026-01-01T10:59:59+00:00"
        )
        == 1
    )
    with pytest.raises(protocol.JournalError, match="^effect_deadline$"):
        protocol.effect_guard(plan, profile, approval, phase, approval["deadline"])
    # Read-only evidence remains valid after the execution window.
    protocol.validate_phase_receipt(
        receipt(protocol, plan, profile, phase), plan, profile, phase, "a" * 64
    )


def test_old_plan_is_readable_but_never_executable(protocol, records):
    plan, profile, approval = records
    plan["schema"] = "deployment-plan-v1"
    plan["phases"] = protocol.phases_for(plan["services"], publish_source=False)
    protocol.validate_plan(plan)
    approval["phases"] = plan["phases"]
    approval["plan_sha256"] = protocol.canonical_sha256(plan)
    with pytest.raises(protocol.JournalError, match="^effect_plan_version$"):
        protocol.effect_guard(plan, profile, approval, "build", "2026-01-01T10:02:00Z")


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("host", "candidate", "/srv/fixture/../application"),
        ("host", "nginx_url", "https://example.invalid"),
        ("host", "nginx_url", "http://127.0.0.1/private"),
        ("host", "nginx_url", "http://credential@127.0.0.1"),
        ("host", "nginx_url", "http://127.0.0.1:99999"),
        ("host", "nginx_url", "\nhttp://127.0.0.1"),
        ("host", "compose_file", "another.yml"),
        ("host", "readiness_timeout_seconds", True),
        ("transport", "ssh_alias", "-oProxyCommand=private"),
        ("transport", "host_python", "python3;private"),
        ("recovery", "recipient_file", "age-secret-value"),
        ("recovery", "local_directory", "/private/./fixture"),
    ],
)
def test_profile_refuses_command_secret_and_unsafe_reference_fields(
    protocol, records, section, field, value
):
    _, profile, _ = records
    profile[section][field] = value
    with pytest.raises(protocol.JournalError) as error:
        protocol.validate_profile(profile)
    assert str(value) not in str(error.value)


def test_profile_rejects_unknown_keys_and_partial_helper_coverage(protocol, records):
    _, profile, _ = records
    altered = copy.deepcopy(profile)
    altered["host"]["run"] = "do-anything"
    with pytest.raises(protocol.JournalError, match="^profile_host$"):
        protocol.validate_profile(altered)
    altered = copy.deepcopy(profile)
    altered["helper_sha256"].pop(next(iter(protocol.HOST_HELPERS)))
    with pytest.raises(protocol.JournalError, match="^profile_helper_pins$"):
        protocol.validate_profile(altered)


@pytest.mark.parametrize(
    "field,value",
    [
        ("operator", " "),
        ("phases", ["build"]),
        ("smoke_calls", []),
        ("data_compatible_rollback", False),
        ("policy", "public-all-channels"),
        ("deadline", "2026-01-01T13:00:00Z"),
        ("approved_at", "2026-01-01T10:00:00"),
    ],
)
def test_broad_or_incomplete_approval_is_not_authority(protocol, records, field, value):
    plan, profile, approval = records
    approval[field] = value
    with pytest.raises(protocol.JournalError):
        protocol.effect_guard(plan, profile, approval, "build", "2026-01-01T10:02:00Z")


def test_profile_or_plan_change_invalidates_existing_approval(protocol, records):
    plan, profile, approval = records
    profile["host"]["operation_root"] = "/srv/fixture/other-operations"
    with pytest.raises(protocol.JournalError, match="^approval_binding$"):
        protocol.validate_approval(approval, plan, profile)


@pytest.mark.parametrize(
    "phase,field,value",
    [
        ("build", "quality_verified", False),
        ("switch_api", "unrelated_preserved", False),
        ("smoke_standard", "attempts", 2),
        ("smoke_standard", "attempts", True),
        ("pause_scheduler", "prior_paused", True),
        ("prechange_backup", "writers_resumed", False),
        ("prechange_backup", "ciphertext_name", "../private.age"),
        ("prechange_backup", "ciphertext_bytes", True),
        ("prechange_restore", "components", ["sqlite"]),
        ("prechange_restore", "scratch_cleanup_verified", False),
        ("prechange_restore", "local_runtime_image_id", "sha256:" + "f" * 64),
        ("prechange_backup", "ciphertext_name", "fixture-backup.tar.gz.gpg"),
        ("publish_source", "candidate_commit", "9" * 40),
        ("resume_scheduler", "original_process_preserved", False),
    ],
)
def test_receipts_cannot_claim_success_from_incomplete_proof(
    protocol, records, phase, field, value
):
    plan, profile, _ = records
    produced = receipt(protocol, plan, profile, phase)
    produced["payload"][field] = value
    with pytest.raises(protocol.JournalError):
        protocol.validate_phase_receipt(produced, plan, profile, phase, "a" * 64)


@pytest.mark.parametrize(
    "field,value",
    [
        ("plan_sha256", "f" * 64),
        ("profile_sha256", "f" * 64),
        ("intent_sha256", "f" * 64),
        ("baseline_sha256", "f" * 64),
        ("phase", "switch_api"),
    ],
)
def test_receipt_substitution_across_operation_or_baseline_refuses(
    protocol, records, field, value
):
    plan, profile, _ = records
    produced = receipt(protocol, plan, profile, "build")
    produced[field] = value
    with pytest.raises(protocol.JournalError, match="^receipt_binding$"):
        protocol.validate_phase_receipt(
            produced, plan, profile, "build", "a" * 64, "b" * 64
        )


@pytest.mark.parametrize(
    "raw",
    [
        b'{"key":1,"key":2}',
        b'{"key":NaN}',
        b'{"key":Infinity}',
        b"[]",
        b'{"password":"private-sensitive-fixture",}',
        b"{}\n{}",
        b"\xff",
    ],
)
def test_malformed_or_duplicate_wire_values_emit_only_closed_code(protocol, raw):
    with pytest.raises(protocol.JournalError, match="^protocol_json$"):
        protocol.decode_object(raw)


def test_wire_size_and_encoding_are_bounded(protocol):
    with pytest.raises(protocol.JournalError, match="^protocol_json$"):
        protocol.decode_object(b" " * (protocol.MAX_RECORD_BYTES + 1))
    with pytest.raises(protocol.JournalError, match="^protocol_json$"):
        protocol.encode_object({"value": float("nan")})
    record = {"b": 2, "a": 1}
    assert protocol.decode_object(protocol.encode_object(record)) == record
    assert protocol.canonical_sha256(record) == protocol.digest(b'{"a":1,"b":2}\n')
    assert json.loads(protocol.encode_object(record)) == record


def test_old_approval_cannot_silently_authorize_physical_consumers(protocol, records):
    plan, profile, approval = records
    approval["schema"] = "deployment-approval-v1"
    with pytest.raises(protocol.JournalError, match="approval_binding"):
        protocol.validate_approval(approval, plan, profile)
    approval["schema"] = "deployment-approval-v2"
    del approval["image_consumers"]
    with pytest.raises(protocol.JournalError, match="approval_schema"):
        protocol.validate_approval(approval, plan, profile)


@pytest.mark.parametrize(
    "consumers",
    [
        {},
        {"api": ["api"]},
        {"api": ["api", "scheduler"], "web": ["web"]},
        {"api": ["matrix-alert-relay", "api"], "web": ["web"]},
        {"api": ["api", "api"], "web": ["web"]},
        {"api": ["api"], "web": ["web", "matrix-alert-relay"]},
    ],
)
def test_approval_refuses_unimplemented_or_missing_consumer_groups(
    protocol, records, consumers
):
    plan, profile, approval = records
    approval["image_consumers"] = consumers
    with pytest.raises(protocol.JournalError, match="approval_consumers"):
        protocol.validate_approval(approval, plan, profile)


@pytest.mark.parametrize("coupled", [False, True])
def test_switch_proof_consumer_scope_must_match_approval(protocol, records, coupled):
    plan, profile, approval = records
    payload = payload_for("switch_api")
    if coupled:
        approval["image_consumers"]["api"].append("matrix-alert-relay")
        payload["consumers"]["matrix-alert-relay"] = {
            "container_id": "4" * 64,
            "image_id": payload["image_id"],
            "ready": True,
        }
    produced = protocol.make_phase_receipt(
        plan,
        profile,
        "switch_api",
        "a" * 64,
        "b" * 64,
        payload,
        "2026-01-01T10:02:00Z",
        "2026-01-01T10:03:00Z",
    )
    protocol.validate_phase_receipt(
        produced, plan, profile, "switch_api", "a" * 64, approval=approval
    )
    approval["image_consumers"]["api"] = (
        ["api"] if coupled else ["api", "matrix-alert-relay"]
    )
    with pytest.raises(protocol.JournalError, match="receipt_consumer_scope"):
        protocol.validate_phase_receipt(
            produced, plan, profile, "switch_api", "a" * 64, approval=approval
        )


@pytest.mark.parametrize(
    "fault", ["image", "duplicate_id", "ready", "extra", "primary"]
)
def test_switch_consumer_proofs_require_distinct_exact_ready_images(
    protocol, records, fault
):
    plan, profile, _ = records
    payload = payload_for("switch_api")
    payload["consumers"]["matrix-alert-relay"] = {
        "container_id": "4" * 64,
        "image_id": payload["image_id"],
        "ready": True,
    }
    if fault == "image":
        payload["consumers"]["matrix-alert-relay"]["image_id"] = "sha256:" + "5" * 64
    elif fault == "duplicate_id":
        payload["consumers"]["matrix-alert-relay"]["container_id"] = payload[
            "container_id"
        ]
    elif fault == "ready":
        payload["consumers"]["matrix-alert-relay"]["ready"] = False
    elif fault == "extra":
        payload["consumers"]["nginx"] = payload["consumers"]["matrix-alert-relay"]
    else:
        payload["container_id"] = "6" * 64
    with pytest.raises(protocol.JournalError, match="receipt_consumers"):
        protocol.make_phase_receipt(
            plan,
            profile,
            "switch_api",
            "a" * 64,
            "b" * 64,
            payload,
            "2026-01-01T10:02:00Z",
            "2026-01-01T10:03:00Z",
        )

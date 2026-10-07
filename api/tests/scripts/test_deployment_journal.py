"""Execute the durable boundaries used by an unattended release controller."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3] / "scripts/lib/deployment_journal.py"
SPEC = importlib.util.spec_from_file_location("deployment_journal", SOURCE)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.fixture
def journal(tmp_path):
    root = tmp_path / "operation"
    root.mkdir(mode=0o700)
    module.exclusive_record(
        root / "plan.json",
        {"schema": "deployment-plan-v1", "phases": ["backup", "switch", "smoke"]},
    )
    return module.DeploymentJournal(root)


def test_normal_sequence_closes_only_after_all_actual_outcomes(journal):
    for phase in ["backup", "switch", "smoke"]:
        assert not journal.status()["completed"]
        token = journal.begin(phase)
        assert journal.status()["needs_attention"]
        journal.finish(phase, token, "succeeded", "a" * 64)
    assert journal.status()["completed"]
    assert not journal.status()["needs_attention"]


def test_killed_writer_leaves_uncertain_effect_that_cannot_be_replayed(journal):
    program = """
import importlib.util, os, sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('journal',sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
journal=module.DeploymentJournal(Path(sys.argv[2]))
journal.begin('backup')
os._exit(17)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", program, str(SOURCE), str(journal.root)]
    )
    assert result.returncode == 17
    recovered = module.DeploymentJournal(journal.root)
    assert recovered.status()["phases"][0]["status"] == "uncertain"
    with pytest.raises(module.JournalError, match="phase_already_attempted"):
        recovered.begin("backup")
    with pytest.raises(module.JournalError, match="prior_phase_incomplete"):
        recovered.begin("switch")


@pytest.mark.parametrize("state", ["failed", "uncertain"])
def test_failed_and_uncertain_outcomes_are_permanent(journal, state):
    token = journal.begin("backup")
    journal.finish("backup", token, state, "a" * 64)
    before = (journal.root / "backup.result.json").read_bytes()
    with pytest.raises(module.JournalError, match="record_already_exists"):
        journal.finish("backup", token, "succeeded", "b" * 64)
    assert (journal.root / "backup.result.json").read_bytes() == before
    with pytest.raises(module.JournalError):
        journal.begin("switch")
    assert not journal.status()["completed"]


def test_second_writer_cannot_enter_an_active_journal(journal):
    program = """
import importlib.util, sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('journal',sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
try:
    module.DeploymentJournal(Path(sys.argv[2])).begin('backup')
except module.JournalError as error:
    print(str(error)); sys.exit(23)
sys.exit(0)
"""
    with journal.locked():
        result = subprocess.run(
            [sys.executable, "-B", "-c", program, str(SOURCE), str(journal.root)],
            capture_output=True,
            text=True,
        )
    assert result.returncode == 23
    assert result.stdout.strip() == "journal_busy"
    assert not (journal.root / "backup.intent.json").exists()


def test_changed_plan_refuses_reads_and_effect_intents(journal):
    path = journal.root / "plan.json"
    path.write_text(json.dumps({"schema": "deployment-plan-v1", "phases": ["switch"]}))
    with pytest.raises(module.JournalError, match="plan_changed"):
        journal.status()
    with pytest.raises(module.JournalError, match="plan_changed"):
        journal.begin("backup")


def test_wrong_intent_or_invalid_evidence_cannot_complete_phase(journal):
    token = journal.begin("backup")
    with pytest.raises(module.JournalError, match="intent_mismatch"):
        journal.finish("backup", "b" * 64, "succeeded", "a" * 64)
    with pytest.raises(module.JournalError, match="evidence_hash"):
        journal.finish("backup", token, "succeeded", "private command output")
    assert not (journal.root / "backup.result.json").exists()


def test_tampered_receipt_cannot_report_success(journal):
    journal.begin("backup")
    module.exclusive_record(
        journal.root / "backup.result.json",
        {"phase": "backup", "status": "succeeded", "intent_sha256": "c" * 64},
    )
    with pytest.raises(module.JournalError, match="result_mismatch"):
        journal.status()


def test_symlinked_journal_and_receipts_refuse(journal, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(journal.root, target_is_directory=True)
    with pytest.raises(module.JournalError, match="journal_symlink"):
        module.DeploymentJournal(alias)
    (journal.root / "backup.intent.json").symlink_to(journal.root / "plan.json")
    with pytest.raises(module.JournalError, match="record_unreadable"):
        journal.status()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_sha256", None),
        ("evidence_sha256", "not-a-digest"),
        ("finished_at", None),
        ("finished_at", "yesterday"),
        ("finished_at", "2026-01-01T01:00:00"),
        ("finished_at", "2000-01-01T01:00:00+00:00"),
    ],
)
def test_reload_rejects_malformed_success_and_blocks_next_effect(journal, field, value):
    token = journal.begin("backup")
    journal.finish("backup", token, "succeeded", "a" * 64)
    path = journal.root / "backup.result.json"
    record = json.loads(path.read_text())
    if value is None:
        record.pop(field)
    else:
        record[field] = value
    path.write_text(json.dumps(record))
    recovered = module.DeploymentJournal(journal.root)
    with pytest.raises(module.JournalError):
        recovered.status()
    with pytest.raises(module.JournalError):
        recovered.begin("switch")
    assert not (journal.root / "switch.intent.json").exists()


def test_reload_rejects_malformed_intent(journal):
    journal.begin("backup")
    path = journal.root / "backup.intent.json"
    record = json.loads(path.read_text())
    record["started_at"] = 42
    path.write_text(json.dumps(record))
    with pytest.raises(module.JournalError, match="record_timestamp"):
        module.DeploymentJournal(journal.root).status()


def test_insecure_or_linked_records_refuse(journal):
    path = journal.root / "plan.json"
    path.chmod(0o644)
    with pytest.raises(module.JournalError, match="unsafe_record"):
        module.DeploymentJournal(journal.root)
    path.chmod(0o600)
    os.link(path, journal.root / "duplicate")
    with pytest.raises(module.JournalError, match="unsafe_record"):
        module.DeploymentJournal(journal.root)


@pytest.mark.parametrize(
    "raw",
    [
        '{"schema":"deployment-plan-v1","phases":["backup"],"phases":["smoke"]}',
        '{"schema":"deployment-plan-v1","phases":["backup","backup"]}',
        '{"schema":"deployment-plan-v1","phases":["../escape"]}',
    ],
)
def test_invalid_plan_never_enters_runtime(journal, raw):
    (journal.root / "plan.json").write_text(raw)
    with pytest.raises(module.JournalError):
        module.DeploymentJournal(journal.root)
    assert not (journal.root / "journal.lock").exists()

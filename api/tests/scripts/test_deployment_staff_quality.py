"""Staff-quality source migration, with real Git and no external effects."""

import ast
import copy
import json
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest
from test_deploy_release import cli, commit, git, plan_args
from test_deploy_release import repository as repository_fixture
from test_deployment_host import host as host_fixture
from test_deployment_host import module as module_fixture
from test_deployment_protocol import protocol as protocol_fixture
from test_deployment_protocol import records as records_fixture

repository = repository_fixture
protocol = protocol_fixture
records = records_fixture
host = host_fixture
module = module_fixture
FLAG = "--include-staff-quality-tools"
COMPOSE = "docker/docker-compose.yml"
EXAMPLE = "docker/.env.example"
OLD_COMMENT = "# Optional staff-only trial: explicit timezone dates, duration <=48h, <=10 paid cases.\n"
NEW_COMMENT = (
    "# Optional Staff-only trial: explicit timezone dates, fixed window <=30 days.\n"
    "# New trials require both model budgets and both conservative price ceilings.\n"
    "# Leave blank until a separately authorized trial is bound; no default spend.\n"
)


@pytest.fixture
def quality_repo(repository, protocol):
    root, _old = repository
    compose = "services:\n  api:\n    environment:\n      - MATRIX_CONTEXT_TRIAL_MAX_CASES=${MATRIX_CONTEXT_TRIAL_MAX_CASES:-10}\n"
    example = (
        OLD_COMMENT
        + "MATRIX_CONTEXT_TRIAL_ID=\nMATRIX_CONTEXT_TRIAL_START_AT=\nMATRIX_CONTEXT_TRIAL_END_AT=\nMATRIX_CONTEXT_TRIAL_MAX_CASES=10\n"
    )
    previous = commit(root, {COMPOSE: compose, EXAMPLE: example})
    additions = "".join(
        f"      - {key}=${{{key}:-}}\n" for key in protocol.STAFF_SPEND_ENV
    )
    env_additions = "".join(f"{key}=\n" for key in protocol.STAFF_SPEND_ENV)
    candidate = commit(
        root,
        {
            COMPOSE: compose + additions,
            EXAMPLE: example.replace(OLD_COMMENT, NEW_COMMENT).replace(
                "MATRIX_CONTEXT_TRIAL_MAX_CASES=10\n",
                "# Historical count-bound descriptors only; not a new spend-bound trial quota.\nMATRIX_CONTEXT_TRIAL_MAX_CASES=10\n"
                + env_additions,
            ),
            **{
                name: "# Offline fixture; never executed by deployment.\n"
                for name in protocol.STAFF_QUALITY_TOOLS
            },
            "api/app/example.py": "VERSION = 2\n",
        },
    )
    return root, previous, candidate


@pytest.fixture
def quality_plan(quality_repo, tmp_path):
    root, previous, candidate = quality_repo
    op = tmp_path / "quality-operation"
    result = cli(*plan_args(root, previous, candidate, op), FLAG)
    assert result.returncode == 0, result.stderr
    return json.loads((op / "plan.json").read_text())


def test_v7_plan_is_exact_inactive_source_bundle(quality_plan, protocol):
    assert quality_plan["schema"] == "deployment-plan-v7"
    assert quality_plan["kind"] == "selective-api-web-with-staff-quality-v1"
    assert set(quality_plan["staff_quality_sha256"]) == protocol.STAFF_QUALITY_FILES
    assert quality_plan["tooling_sha256"] == {}
    assert quality_plan["services"] == ["api"]
    assert quality_plan["phases"] == protocol.phases_for(["api"])
    for fault in ("extra", "missing", "malformed"):
        bad = copy.deepcopy(quality_plan)
        pins = bad["staff_quality_sha256"]
        if fault == "extra":
            pins["scripts/unreviewed.py"] = "a" * 64
        elif fault == "missing":
            del pins[COMPOSE]
        else:
            pins[COMPOSE] = "bad"
        with pytest.raises(protocol.JournalError):
            protocol.validate_plan(bad)
    bad = copy.deepcopy(quality_plan)
    bad["services"] = ["web"]
    bad["phases"] = protocol.phases_for(["web"])
    with pytest.raises(protocol.JournalError, match="staff_quality_requires_api"):
        protocol.validate_plan(bad)


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--include-deployment-tooling"],
        [FLAG, "--include-staff-pilot-monitoring"],
        [FLAG, "--include-retention-monitoring"],
        [FLAG, "--preserve-bisq2-heap-repair"],
        [FLAG, "--include-python-runner-pins"],
    ],
)
def test_prior_or_mixed_capabilities_refuse_quality_bundle(
    quality_repo, tmp_path, flags
):
    root, previous, candidate = quality_repo
    op = tmp_path / "refused"
    assert cli(*plan_args(root, previous, candidate, op), *flags).returncode == 2
    assert not op.exists()


@pytest.mark.parametrize(
    "fault",
    [
        "nonempty_default",
        "renamed_key",
        "other_compose",
        "other_example",
        "partial",
        "delete",
        "symlink",
        "executable",
        "unknown_script",
    ],
)
def test_v7_rejects_configuration_or_tool_scope_expansion(
    quality_repo, protocol, tmp_path, fault
):
    root, previous, candidate = quality_repo
    name = sorted(protocol.STAFF_QUALITY_TOOLS)[0]
    changes = {}
    if fault == "nonempty_default":
        changes[COMPOSE] = (
            (root / COMPOSE).read_text().replace("BUDGET_USD:-}", "BUDGET_USD:-60}", 1)
        )
    elif fault == "renamed_key":
        changes[COMPOSE] = (
            (root / COMPOSE)
            .read_text()
            .replace("MATRIX_CONTEXT_TRIAL_BUDGET_USD", "OTHER_BUDGET")
        )
    elif fault == "other_compose":
        changes[COMPOSE] = (
            root / COMPOSE
        ).read_text() + "      - MATRIX_SYNC_ENABLED=true\n"
    elif fault == "other_example":
        changes[EXAMPLE] = (root / EXAMPLE).read_text() + "UNREVIEWED=1\n"
    elif fault == "partial":
        changes[COMPOSE] = (
            (root / COMPOSE)
            .read_text()
            .replace(
                "      - MATRIX_CONTEXT_TRIAL_BUDGET_USD=${MATRIX_CONTEXT_TRIAL_BUDGET_USD:-}\n",
                "",
            )
        )
    elif fault == "delete":
        changes[name] = None
    elif fault == "symlink":
        (root / name).unlink()
        (root / name).symlink_to("summarize_staff_context.py")
    elif fault == "executable":
        (root / name).chmod(0o755)
        git(root, "update-index", "--chmod=+x", name)
    else:
        changes["api/app/scripts/unreviewed.py"] = "raise SystemExit(0)\n"
    candidate = commit(root, changes)
    op = tmp_path / "refused"
    assert cli(*plan_args(root, previous, candidate, op), FLAG).returncode == 2
    assert not op.exists()


def test_controller_changes_still_require_separate_tooling_capability(
    quality_repo, tmp_path
):
    root, previous, candidate = quality_repo
    candidate = commit(
        root, {"scripts/deploy_release.py": "# reviewed controller fixture\n"}
    )
    args = plan_args(root, previous, candidate, tmp_path / "op")
    assert cli(*args, FLAG).returncode == 2
    result = cli(*args, FLAG, "--include-deployment-tooling")
    assert result.returncode == 0, result.stderr
    plan = json.loads((tmp_path / "op/plan.json").read_text())
    assert set(plan["tooling_sha256"]) == {"scripts/deploy_release.py"}


def test_v7_approval_and_receipt_join_exact_source_pins(
    records, quality_plan, protocol
):
    plan, profile, approval = copy.deepcopy(records)
    for field in ("schema", "kind", "tooling_sha256", "staff_quality_sha256"):
        plan[field] = quality_plan[field]
    approval.update(
        schema="deployment-approval-v7",
        plan_sha256=protocol.canonical_sha256(plan),
        tooling_sha256={},
        staff_quality_sha256=copy.deepcopy(plan["staff_quality_sha256"]),
    )
    protocol.validate_approval(approval, plan, profile)
    protocol.effect_guard(plan, profile, approval, "build", "2026-01-01T10:30:00+00:00")
    for field in ("tooling_sha256", "staff_quality_sha256"):
        bad = copy.deepcopy(approval)
        bad[field] = {"unreviewed": "a" * 64}
        with pytest.raises(protocol.JournalError):
            protocol.validate_approval(bad, plan, profile)
    with pytest.raises(protocol.JournalError):
        protocol.validate_approval(
            dict(approval, schema="deployment-approval-v3"), plan, profile
        )
    payload = {
        key: plan["source"][key]
        for key in ("candidate_commit", "candidate_tree", "previous_commit")
    }
    payload.update(
        source_clean=True, unrelated_preserved=True, staff_quality_config_preserved=True
    )
    protocol._validate_payload("publish_source", payload, plan)
    for value in (False, None):
        bad = dict(payload, staff_quality_config_preserved=value)
        with pytest.raises(protocol.JournalError):
            protocol._validate_payload("publish_source", bad, plan)


def test_source_publication_preserves_runtime_values_and_rechecks_host_pins(
    quality_repo, quality_plan, protocol, module, tmp_path
):
    root, previous, candidate = quality_repo
    host = module.DeploymentHost.__new__(module.DeploymentHost)
    host.plan = quality_plan
    host.candidate = root
    host.install = tmp_path / "install"
    subprocess.run(
        ["git", "clone", "--quiet", str(root), str(host.install)], check=True
    )
    git(host.install, "checkout", "--quiet", "--detach", previous)
    git(host.install, "config", "user.name", "Fixture")
    git(host.install, "config", "user.email", "fixture@example.invalid")
    (host.install / ".git/info/exclude").write_text("docker/.env\n")
    env = host.install / "docker/.env"
    env.write_text("MATRIX_SYNC_ENABLED=false\nPRESERVED_SETTING=fixture\n")
    before = env.read_bytes()
    host.approval = {
        key: copy.deepcopy(quality_plan[key])
        for key in ("tooling_sha256", "staff_quality_sha256")
    }
    host._git = lambda path, *args: git(path, *args).decode().strip()

    def config(*args):
        assert args == ("config",)
        settings = {"MATRIX_SYNC_ENABLED": "false", "PRESERVED_SETTING": "fixture"}
        if git(host.install, "rev-parse", "HEAD").decode().strip() == candidate:
            settings.update({key: "" for key in protocol.STAFF_SPEND_ENV})
        return json.dumps({"services": {"api": {"environment": settings}}}).encode()

    host._shell = config
    host.baseline = {
        "compose_sha256": module.digest(module.encode(json.loads(config("config")))),
        "env_sha256": module.digest(before),
    }
    host._inspect = lambda: {}
    host._preserved = lambda _containers: None
    result = host._publish()
    assert result["staff_quality_config_preserved"] is True
    assert env.read_bytes() == before
    assert git(host.install, "rev-parse", "HEAD").decode().strip() == candidate
    host._configuration()
    host.approval["staff_quality_sha256"] = {}
    with pytest.raises(module.JournalError, match="host_staff_quality_source"):
        host._source(published=True)


@pytest.mark.parametrize(
    "fault", ["nonempty", "partial", "other_setting", "other_service"]
)
def test_config_comparison_only_normalizes_exact_empty_api_bundle(
    host, module, protocol, fault
):
    host.plan["schema"] = "deployment-plan-v7"
    before = {
        "services": {
            "api": {"environment": {"PRESERVED": "same"}},
            "web": {"environment": {}},
        }
    }
    after = copy.deepcopy(before)
    after["services"]["api"]["environment"].update(
        {key: "" for key in protocol.STAFF_SPEND_ENV}
    )
    assert host._staff_quality_config(after) == before
    if fault == "nonempty":
        after["services"]["api"]["environment"][protocol.STAFF_SPEND_ENV[0]] = "60"
    elif fault == "partial":
        del after["services"]["api"]["environment"][protocol.STAFF_SPEND_ENV[0]]
    elif fault == "other_setting":
        after["services"]["api"]["environment"]["PRESERVED"] = "changed"
    else:
        after["services"]["web"]["environment"][protocol.STAFF_SPEND_ENV[0]] = ""
    if fault in {"nonempty", "partial"}:
        with pytest.raises(module.JournalError):
            host._staff_quality_config(after)
    else:
        assert host._staff_quality_config(after) != before


@pytest.mark.parametrize(
    "line",
    [
        "MATRIX_CONTEXT_TRIAL_BUDGET_USD=60",
        "MATRIX_CONTEXT_TRIAL_BUDGET_USD:60",
        "MATRIX_CONTEXT_TRIAL_BUDGET_USD: 60",
        "export MATRIX_CONTEXT_TRIAL_BUDGET_USD:60",
        "export MATRIX_CONTEXT_TRIAL_BUDGET_USD=60",
        "'MATRIX_CONTEXT_TRIAL_BUDGET_USD'=60",
        'MATRIX_CONTEXT_TRIAL_BUDGET_USD="${VALUE}"',
        "MATRIX_CONTEXT_TRIAL_BUDGET_USD=\nMATRIX_CONTEXT_TRIAL_BUDGET_USD=",
    ],
)
def test_nonempty_or_ambiguous_dotenv_assignment_fails_before_runtime_inspection(
    host, module, monkeypatch, line
):
    host.plan["schema"] = "deployment-plan-v7"
    (host.install / "docker/.env").write_text(line + "\n")
    monkeypatch.setattr(module, "verify_inherited_lock", lambda *_a: None)
    for name in ("_marker", "_helpers", "_source"):
        setattr(host, name, lambda **_kw: None)
    host._state = lambda: {}
    host._inspect = lambda: pytest.fail(
        "configuration must be rejected before runtime work"
    )
    with pytest.raises(module.JournalError, match="host_staff_quality_environment"):
        host.preflight()


@pytest.mark.parametrize("schema", ["deployment-plan-v2", "deployment-plan-v7"])
def test_only_v7_api_replacement_allows_absent_to_empty_bundle(
    host, module, protocol, schema
):
    host.plan["schema"] = schema
    before = host.baseline["containers"]["api"]
    current = copy.deepcopy(before)
    current["Config"]["Env"].extend(f"{key}=" for key in protocol.STAFF_SPEND_ENV)
    if schema == "deployment-plan-v7":
        host._replacement("api", current, current["Image"])
        current["Config"]["Env"][-1] += "20"
        with pytest.raises(module.JournalError, match="host_staff_quality_environment"):
            host._replacement("api", current, current["Image"])
    else:
        with pytest.raises(module.JournalError, match="host_replacement_configuration"):
            host._replacement("api", current, current["Image"])


@pytest.mark.parametrize("schema", ["deployment-plan-v2", "deployment-plan-v7"])
def test_only_v7_accepts_exact_empty_additive_review_schema(host, module, schema):
    host.plan["schema"] = schema
    data = host.install / "api/data"
    data.mkdir(parents=True, exist_ok=True)
    database = data / "escalations.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.executescript(
            "CREATE TABLE escalations(id INTEGER, channel TEXT, channel_metadata TEXT, question TEXT); INSERT INTO escalations VALUES (1,'matrix',NULL,'Preserved question');"
        )
    before = module.DeploymentHost._preserved_data(host, host.fixture_state)
    with closing(sqlite3.connect(database)) as db, db:
        db.executescript(
            "ALTER TABLE escalations ADD COLUMN staff_context_verdicts TEXT NOT NULL DEFAULT '[]';"
        )
        for ddl in module.STAFF_QUALITY_LEDGER_DDL.values():
            db.execute(ddl)
    after = module.DeploymentHost._preserved_data(host, host.fixture_state)
    host.baseline["protected_data"] = before
    assert host._protected_data_preserved(after) is (schema == "deployment-plan-v7")
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("UPDATE escalations SET question='Changed historical fact'")
    assert module.DeploymentHost._preserved_data(host, host.fixture_state) != after


@pytest.mark.parametrize(
    "fault",
    [
        "verdict_value",
        "wrong_default",
        "other_column",
        "verdict_row",
        "answer_row",
        "spend_row",
    ],
)
def test_v7_migration_exception_never_hides_history_or_new_work(host, module, fault):
    host.plan["schema"] = "deployment-plan-v7"
    data = host.install / "api/data"
    data.mkdir(parents=True, exist_ok=True)
    database = data / "escalations.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.executescript(
            "CREATE TABLE escalations(id INTEGER, channel TEXT, channel_metadata TEXT); INSERT INTO escalations VALUES (1,'matrix',NULL);"
        )
    before = module.DeploymentHost._preserved_data(host, host.fixture_state)
    with closing(sqlite3.connect(database)) as db, db:
        if fault == "other_column":
            db.execute("ALTER TABLE escalations ADD COLUMN other TEXT")
        elif fault.endswith("_row"):
            table = {
                "verdict_row": "matrix_context_verdict_events",
                "answer_row": "matrix_context_answer_events",
                "spend_row": "matrix_context_trial_spend",
            }[fault]
            db.execute(module.STAFF_QUALITY_LEDGER_DDL[table])
            if fault == "spend_row":
                db.execute(
                    "INSERT INTO matrix_context_trial_spend "
                    "(trial_id,escalation_id,kind,call_id,started_at,utc_day,"
                    "input_tokens_bound,max_output_tokens,reserved_nanodollars,status) "
                    "VALUES('trial',1,'gate','call','2026-01-01T00:00:00+00:00',"
                    "'2026-01-01',1,10,100,'uncertain')"
                )
            else:
                db.execute(
                    "INSERT INTO "
                    + table
                    + " (event_id,room_id) VALUES('event','room')"
                )
        else:
            default = "'[1]'" if fault == "wrong_default" else "'[]'"
            db.execute(
                "ALTER TABLE escalations ADD COLUMN staff_context_verdicts TEXT NOT NULL DEFAULT "
                + default
            )
            db.execute("UPDATE escalations SET staff_context_verdicts='[]'")
            if fault == "verdict_value":
                db.execute("UPDATE escalations SET staff_context_verdicts='[{}]'")
    if fault == "other_column":
        assert module.DeploymentHost._preserved_data(host, host.fixture_state) != before
    else:
        reason = (
            "host_staff_quality_ledger_not_empty"
            if fault.endswith("_row")
            else "host_staff_quality_verdict_migration"
        )
        with pytest.raises(module.JournalError, match=reason):
            module.DeploymentHost._preserved_data(host, host.fixture_state)


def test_migration_contract_matches_actual_application_ddl(module):
    root = Path(__file__).resolve().parents[3]
    observed = {}
    for name in ("context_feedback.py", "context_trial.py"):
        tree = ast.parse((root / "api/app/channels/staff_assist" / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value.strip().replace(
                    "CREATE TABLE IF NOT EXISTS", "CREATE TABLE"
                )
                for table in module.STAFF_QUALITY_LEDGER_DDL:
                    if text.startswith("CREATE TABLE " + table + " "):
                        observed[table] = module._schema_tokens(text)
    assert observed == {
        table: module._schema_tokens(ddl)
        for table, ddl in module.STAFF_QUALITY_LEDGER_DDL.items()
    }


@pytest.mark.parametrize(
    "table",
    [
        "matrix_context_verdict_events",
        "matrix_context_answer_events",
        "matrix_context_trial_spend",
    ],
)
@pytest.mark.parametrize(
    "fault", ["wrong_columns", "missing_primary_key", "missing_constraint"]
)
def test_empty_but_malformed_new_ledger_is_not_preservation(host, module, table, fault):
    host.plan["schema"] = "deployment-plan-v7"
    data = host.install / "api/data"
    data.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(data / "escalations.db")) as db, db:
        db.executescript(
            "CREATE TABLE escalations(id INTEGER PRIMARY KEY, channel TEXT, channel_metadata TEXT);"
        )
        ddl = module.STAFF_QUALITY_LEDGER_DDL[table]
        if fault == "wrong_columns":
            ddl = "CREATE TABLE " + table + " (unrelated TEXT)"
        elif fault == "missing_primary_key":
            ddl = (
                ddl.replace(" PRIMARY KEY", "", 1)
                if "event_id TEXT PRIMARY KEY" in ddl
                else ddl.replace(
                    ", PRIMARY KEY (trial_id, escalation_id, kind, call_id)", ""
                )
            )
        else:
            ddl = (
                ddl.replace(" REFERENCES escalations(id) ON DELETE CASCADE", "")
                if "REFERENCES" in ddl
                else ddl.replace(" NOT NULL", "", 1)
            )
        assert ddl != module.STAFF_QUALITY_LEDGER_DDL[table]
        db.execute(ddl)
    with pytest.raises(module.JournalError, match="host_staff_quality_ledger_schema"):
        module.DeploymentHost._preserved_data(host, host.fixture_state)


def test_rehearsal_migration_check_retains_all_old_schema_rows_and_files(
    tmp_path, module
):
    from test_deployment_rehearsal import database_snapshot, verify_quality_migration

    database = tmp_path / "fixture.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.executescript(
            "CREATE TABLE escalations(id INTEGER PRIMARY KEY, channel TEXT); INSERT INTO escalations VALUES(1,'matrix'); CREATE TABLE retained(value TEXT); INSERT INTO retained VALUES('unchanged');"
        )
    before = database_snapshot(database)
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "ALTER TABLE escalations ADD COLUMN staff_context_verdicts TEXT NOT NULL DEFAULT '[]'"
        )
        for ddl in module.STAFF_QUALITY_LEDGER_DDL.values():
            db.execute(ddl)
    after = database_snapshot(database)
    verify_quality_migration(before, after, module.STAFF_QUALITY_LEDGER_DDL)
    for table, field in (
        ("escalations", "rows"),
        ("retained", "rows"),
        ("retained", "sql"),
        ("matrix_context_trial_spend", "sql"),
    ):
        bad = copy.deepcopy(after)
        bad[table][field] = (
            [] if field == "rows" else "CREATE TABLE changed(value TEXT)"
        )
        with pytest.raises(AssertionError):
            verify_quality_migration(before, bad, module.STAFF_QUALITY_LEDGER_DDL)


@pytest.mark.parametrize("count", range(5))
def test_preflight_spend_bundle_matches_replacement_contract(
    host, module, protocol, count
):
    host.plan["schema"] = "deployment-plan-v7"
    current = copy.deepcopy(host.fixture_state)
    current["api"]["Config"]["Env"].extend(
        f"{name}=false" for name in module.DISABLED_FLAGS
    )
    current["api"]["Config"]["Env"].extend(
        f"{name}=" for name in protocol.STAFF_SPEND_ENV[:count]
    )
    data = host.install / "api/data"
    data.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(data / "feedback.db")) as db, db:
        db.executescript(
            "CREATE TABLE channel_autoresponse_policy(channel_id,enabled,generation_enabled); INSERT INTO channel_autoresponse_policy VALUES('matrix',0,0),('bisq2',0,0); CREATE TABLE channel_launch_global(singleton_id,autonomous_delivery_enabled); INSERT INTO channel_launch_global VALUES(1,0);"
        )
    if count in (0, 4):
        module.DeploymentHost._disabled(host, current)
    else:
        with pytest.raises(module.JournalError, match="host_staff_quality_environment"):
            module.DeploymentHost._disabled(host, current)


@pytest.mark.parametrize(
    "object_name",
    [
        "matrix_context_verdict_events",
        "matrix_context_answer_events",
        "matrix_context_trial_spend",
        "staff_context_verdicts",
    ],
)
def test_preexisting_empty_addition_cannot_be_removed(host, module, object_name):
    host.plan["schema"] = "deployment-plan-v7"
    data = host.install / "api/data"
    data.mkdir(parents=True, exist_ok=True)
    database = data / "escalations.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "CREATE TABLE escalations(id INTEGER, channel TEXT, channel_metadata TEXT)"
        )
        if object_name == "staff_context_verdicts":
            db.execute(
                "ALTER TABLE escalations ADD COLUMN staff_context_verdicts TEXT NOT NULL DEFAULT '[]'"
            )
        else:
            db.execute(module.STAFF_QUALITY_LEDGER_DDL[object_name])
    host.baseline["protected_data"] = module.DeploymentHost._preserved_data(
        host, host.fixture_state
    )
    with closing(sqlite3.connect(database)) as db, db:
        if object_name == "staff_context_verdicts":
            db.execute("ALTER TABLE escalations DROP COLUMN staff_context_verdicts")
        else:
            db.execute("DROP TABLE " + object_name)
    assert not host._protected_data_preserved(
        module.DeploymentHost._preserved_data(host, host.fixture_state)
    )


@pytest.mark.parametrize(
    "object_name",
    [
        "matrix_context_verdict_events",
        "matrix_context_answer_events",
        "matrix_context_trial_spend",
    ],
)
def test_view_cannot_impersonate_absent_ledger(host, module, object_name):
    host.plan["schema"] = "deployment-plan-v7"
    data = host.install / "api/data"
    data.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(data / "escalations.db")) as db, db:
        db.execute(
            "CREATE TABLE escalations(id INTEGER, channel TEXT, channel_metadata TEXT)"
        )
        db.execute("CREATE VIEW " + object_name + " AS SELECT 1 AS event_id")
    with pytest.raises(module.JournalError, match="host_staff_quality_ledger_schema"):
        module.DeploymentHost._preserved_data(host, host.fixture_state)


def test_extra_verdict_column_constraint_is_not_reviewed_migration(host, module):
    host.plan["schema"] = "deployment-plan-v7"
    data = host.install / "api/data"
    data.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(data / "escalations.db")) as db, db:
        db.execute(
            "CREATE TABLE escalations(id INTEGER, channel TEXT, channel_metadata TEXT, staff_context_verdicts TEXT NOT NULL DEFAULT '[]' CHECK(staff_context_verdicts='[]'))"
        )
    with pytest.raises(
        module.JournalError, match="host_staff_quality_verdict_migration"
    ):
        module.DeploymentHost._preserved_data(host, host.fixture_state)


@pytest.mark.parametrize(
    "constraint",
    [
        "CHECK(staff_context_verdicts='[]')",
        'UNIQUE("staff_context_verdicts")',
        "UNIQUE('staff_context_verdicts')",
        "CONSTRAINT frozen CHECK([STAFF_CONTEXT_VERDICTS]='[]')",
    ],
)
def test_table_constraint_cannot_hide_verdict_write_failure(host, module, constraint):
    host.plan["schema"] = "deployment-plan-v7"
    data = host.install / "api/data"
    data.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(data / "escalations.db")) as db, db:
        db.execute(
            "CREATE TABLE escalations(id INTEGER, channel TEXT, channel_metadata TEXT, "
            "staff_context_verdicts TEXT NOT NULL DEFAULT '[]', " + constraint + ")"
        )
        db.execute("INSERT INTO escalations(id,channel) VALUES(1,'matrix')")
        with pytest.raises(sqlite3.IntegrityError):
            if constraint.startswith("UNIQUE"):
                db.execute("INSERT INTO escalations(id,channel) VALUES(2,'matrix')")
            else:
                db.execute(
                    "UPDATE escalations SET staff_context_verdicts='[{}]' WHERE id=1"
                )
    with pytest.raises(
        module.JournalError, match="host_staff_quality_verdict_migration"
    ):
        module.DeploymentHost._preserved_data(host, host.fixture_state)


def test_unrelated_existing_constraint_preserved_by_verdict_migration(host, module):
    host.plan["schema"] = "deployment-plan-v7"
    data = host.install / "api/data"
    data.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(data / "escalations.db")) as db, db:
        db.execute(
            "CREATE TABLE escalations(id INTEGER, channel TEXT, channel_metadata TEXT, "
            "staff_context_verdicts TEXT NOT NULL DEFAULT '[]', "
            "CHECK(channel IN ('matrix','web')))"
        )
        db.execute("INSERT INTO escalations(id,channel) VALUES(1,'matrix')")
    result = module.DeploymentHost._preserved_data(host, host.fixture_state)
    assert result["staff_quality_presence"]["staff_context_verdicts"] is True
    assert result["tables"]["matrix_cases"]["count"] == 1


@pytest.mark.parametrize(
    "extra",
    [
        "CREATE UNIQUE INDEX unique_channel ON escalations(channel)",
        "CREATE TRIGGER immutable_question BEFORE UPDATE ON escalations BEGIN SELECT RAISE(ABORT,'blocked'); END",
        "CREATE VIEW hidden_cases AS SELECT * FROM escalations",
    ],
)
def test_rehearsal_schema_comparison_rejects_unreviewed_objects(
    tmp_path, module, extra
):
    from test_deployment_rehearsal import database_snapshot, verify_quality_migration

    database = tmp_path / "schema.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "CREATE TABLE escalations(id INTEGER, channel TEXT, channel_metadata TEXT)"
        )
    before = database_snapshot(database)
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "ALTER TABLE escalations ADD COLUMN staff_context_verdicts TEXT NOT NULL DEFAULT '[]'"
        )
        for ddl in module.STAFF_QUALITY_LEDGER_DDL.values():
            db.execute(ddl)
        db.execute(extra)
    with pytest.raises(AssertionError):
        verify_quality_migration(
            before, database_snapshot(database), module.STAFF_QUALITY_LEDGER_DDL
        )

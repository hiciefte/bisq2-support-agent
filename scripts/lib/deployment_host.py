"""Selective, source-only host effects under the canonical lifecycle lock.

The stdio owner supplies phase ordering/approval and remains alive while local
recovery is verified. This backend stores private observations and exclusive
effect records; reconnecting never supplies a new baseline or retries an intent.
"""

from __future__ import annotations

import io
import json
import os
import re
import signal
import sqlite3
import stat
import subprocess
import tarfile
import time
import uuid
from contextlib import closing
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Callable, cast

from .deployment_journal import (
    JournalError,
    digest,
    encode,
    exclusive_record,
    is_digest,
    now,
    read_record,
    require,
    timestamp,
)
from .docker_identity import container_identity_sha256
from .lifecycle_lock import verify_inherited_lock

SCRIPTS = Path(__file__).resolve().parents[1]
SHELL = SCRIPTS / "lib/deployment_host.sh"
DISABLED_FLAGS = (
    "MATRIX_SYNC_ENABLED",
    "MATRIX_CHATOPS_ENABLED",
    "BISQ2_CHANNEL_ENABLED",
    "BISQ2_CHATOPS_ENABLED",
    "ESCALATION_BISQ2_WS_ENABLED",
    "AUTONOMOUS_DELIVERY_ENABLED",
)


class HostCommandError(JournalError):
    def __init__(self, code: str, *, uncertain: bool = False):
        super().__init__(code)
        self.uncertain = uncertain


def private_bytes(path: Path, value: bytes) -> None:
    require(len(value) <= 8 * 1024 * 1024, "host_evidence_size")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def private_json(path: Path) -> dict:
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "host_private_duplicate_key")
            value[key] = item
        return value

    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_uid == os.geteuid()
            and info.st_nlink == 1
            and info.st_size <= 8 * 1024 * 1024,
            "host_private_evidence",
        )
        value = json.loads(stream.read(), object_pairs_hook=pairs)
    require(isinstance(value, dict), "host_private_object")
    return value


class CommandRunner:
    """No output forwarding; timeouts preserve uncertainty rather than retry."""

    def __init__(self, root: Path, inherited_fd: int):
        self.root = root
        self.inherited_fd = inherited_fd

    def run(
        self,
        argv: list[str],
        label: str,
        timeout: int,
        *,
        input_bytes: bytes | None = None,
    ) -> bytes:
        require(bool(re.fullmatch(r"[a-z0-9_-]{1,90}", label)), "host_command_label")
        require(1 <= timeout <= 1800, "host_command_timeout")
        # Preserve ordinary operator tool discovery but drop ambient application,
        # Docker/Compose, Git, smoke-question and provider configuration overrides.
        env = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}
        }
        env.update(
            BISQ_SUPPORT_LIFECYCLE_LOCK_FD=str(self.inherited_fd),
            BISQ_SUPPORT_DEPLOYMENT_PLAN_SHA256=os.environ.get(
                "BISQ_SUPPORT_DEPLOYMENT_PLAN_SHA256", ""
            ),
            GIT_OPTIONAL_LOCKS="0",
            GIT_NO_LAZY_FETCH="1",
            GIT_TERMINAL_PROMPT="0",
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
        )
        exclusive_record(
            self.root / f"{label}.intent.json",
            {"argv_sha256": digest(encode(argv)), "started_at": now()},
        )
        stdout_path = self.root / f"{label}.stdout"
        stderr_path = self.root / f"{label}.stderr"
        stdout_fd = os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        stderr_fd = os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(stdout_fd, "wb") as stdout, os.fdopen(stderr_fd, "wb") as stderr:
            try:
                child = subprocess.Popen(
                    argv,
                    stdin=(
                        subprocess.PIPE
                        if input_bytes is not None
                        else subprocess.DEVNULL
                    ),
                    stdout=stdout,
                    stderr=stderr,
                    env=env,
                    pass_fds=(self.inherited_fd,),
                    start_new_session=True,
                )
                child.communicate(input=input_bytes, timeout=timeout)
            except subprocess.TimeoutExpired as error:
                # Contain the entire local command group, including inherited
                # lock descriptors. A Docker/provider request may have arrived.
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=2)
                raise HostCommandError(
                    "host_command_timeout", uncertain=True
                ) from error
            except OSError as error:
                raise HostCommandError("host_command_unavailable") from error
        require(
            stdout_path.stat().st_size <= 8 * 1024 * 1024
            and stderr_path.stat().st_size <= 8 * 1024 * 1024,
            "host_command_output_limit",
        )
        out, err = stdout_path.read_bytes(), stderr_path.read_bytes()
        exclusive_record(
            self.root / f"{label}.result.json",
            {
                "returncode": child.returncode,
                "stdout_sha256": digest(out),
                "stderr_sha256": digest(err),
                "finished_at": now(),
            },
        )
        if child.returncode != 0:
            raise HostCommandError("host_command_failed")
        return out


def image_id(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", value))


def container_id(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def immutable(container: dict) -> str:
    fields = {
        key: container[key] for key in ("Id", "Image", "Created", "Config", "Mounts")
    }
    return container_identity_sha256(encode(fields), container["Id"])


def process_identity(container: dict) -> dict:
    state = container["State"]
    return {
        "pid": state["Pid"],
        "started_at": state["StartedAt"],
        "restart_count": container["RestartCount"],
    }


class DeploymentHost:
    def __init__(
        self, plan: dict, profile: dict, approval: dict, operation: Path, runner=None
    ):
        from .deployment_protocol import (
            canonical_sha256,
            validate_approval,
            validate_plan,
            validate_profile,
        )

        validate_plan(plan)
        validate_profile(profile)
        validate_approval(approval, plan, profile)
        self.plan, self.profile, self.approval = plan, profile, approval
        self.host = profile["host"]
        self.install = Path(self.host["repository"])
        self.candidate = Path(self.host["candidate"])
        self.operation = operation
        require(
            operation == Path(self.host["operation_root"]) / canonical_sha256(plan),
            "host_operation_root",
        )
        require(
            plan["schema"] in {"deployment-plan-v2", "deployment-plan-v3"},
            "host_plan_version",
        )
        for path in (operation, self.install, self.candidate):
            require(
                path.is_absolute()
                and path.resolve(strict=True) == path
                and not any(p.is_symlink() for p in (path, *path.parents)),
                "host_path",
            )
        self.lock_fd = int(os.environ.get("BISQ_SUPPORT_LIFECYCLE_LOCK_FD", "-1"))
        verify_inherited_lock(self.install, self.lock_fd)
        self.root = operation / "host"
        if not self.root.exists():
            self.root.mkdir(mode=0o700)
        info = self.root.lstat()
        require(
            stat.S_ISDIR(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o700
            and info.st_uid == os.geteuid(),
            "host_operation_private",
        )
        self.commands = self.root / "commands"
        if not self.commands.exists():
            self.commands.mkdir(mode=0o700)
        self.runner = runner or CommandRunner(self.commands, self.lock_fd)
        self.session = uuid.uuid4().hex[:12]
        self.counter = 0
        self.pause_expected = None
        self.effect_until: datetime | None = None
        self.baseline = None
        self.baseline_sha256 = None
        self.expected: dict[str, dict] = {}

    @property
    def active_marker(self):
        return self.install / "failed_updates/disaster-recovery/deployment-active.json"

    def _marker_record(self):
        return {
            "schema": "deployment-active-v1",
            "plan_sha256": digest(encode(self.plan)),
            "profile_sha256": digest(encode(self.profile)),
            "operation": str(self.operation),
        }

    def _marker(self, *, create=False):
        path = self.active_marker
        if path.exists() or path.is_symlink():
            require(
                read_record(path) == self._marker_record(),
                "host_other_operation_active",
            )
            require(
                (self.root / "baseline.private.json").exists(),
                "host_active_baseline_missing",
            )
        elif create:
            exclusive_record(path, self._marker_record())

    def _run(self, argv, label, timeout=30, *, input_bytes=None):
        self.counter += 1
        remaining = int(
            (
                min(
                    timestamp(self.plan["deadline"]),
                    timestamp(self.approval["deadline"]),
                )
                - timestamp(now())
            ).total_seconds()
        )
        if self.effect_until is not None:
            remaining = min(
                remaining, int((self.effect_until - timestamp(now())).total_seconds())
            )
        require(remaining > 0, "host_deadline")
        return self.runner.run(
            argv,
            f"{self.session}-{self.counter:05d}-{label}",
            min(timeout, remaining),
            input_bytes=input_bytes,
        )

    def _shell(self, action, *args, timeout=30):
        return self._run(
            [
                "bash",
                str(SHELL),
                action,
                str(self.install),
                self.host["compose_project"],
                *map(str, args),
            ],
            action,
            timeout,
        )

    def _git(self, path, *args):
        return (
            self._run(
                [
                    "git",
                    "--no-replace-objects",
                    "-C",
                    str(path),
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "safe.directory=" + str(path),
                    *args,
                ],
                "git",
            )
            .decode()
            .strip()
        )

    def _source(self, published=False):
        from deploy_release import changed_paths, classify_services, tooling_hashes

        source = self.plan["source"]
        for path, prefix in (
            (self.install, "candidate" if published else "previous"),
            (self.candidate, "candidate"),
        ):
            require(
                self._git(path, "rev-parse", "HEAD") == source[prefix + "_commit"],
                "host_source_head",
            )
            require(
                self._git(path, "rev-parse", "HEAD^{tree}") == source[prefix + "_tree"],
                "host_source_tree",
            )
            require(
                not self._git(
                    path, "status", "--porcelain=v1", "--untracked-files=normal"
                ),
                "host_source_dirty",
            )
            flags = self._git(path, "ls-files", "-v").splitlines()
            require(
                all(line.startswith("H ") for line in flags), "host_source_index_flags"
            )
        paths = changed_paths(
            self.candidate, source["previous_commit"], source["candidate_commit"]
        )
        require(
            digest(encode(paths)) == source["changed_paths_sha256"], "host_source_diff"
        )
        tooling = self.plan["schema"] == "deployment-plan-v3"
        require(
            classify_services(paths, include_deployment_tooling=tooling)
            == self.plan["services"],
            "host_source_scope",
        )
        if tooling:
            require(
                tooling_hashes(self.candidate, source["candidate_commit"], paths)
                == self.plan["tooling_sha256"],
                "host_source_tooling",
            )
            require(
                self.approval["tooling_sha256"] == self.plan["tooling_sha256"],
                "approval_tooling",
            )
        self._git(
            self.candidate,
            "merge-base",
            "--is-ancestor",
            source["previous_commit"],
            source["candidate_commit"],
        )
        self._git(
            self.install, "cat-file", "-e", source["candidate_commit"] + "^{commit}"
        )

    def _inspect(self):
        ids = (
            self._run(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--no-trunc",
                    "-q",
                    "--filter",
                    "label=com.docker.compose.project=" + self.host["compose_project"],
                ],
                "containers",
            )
            .decode()
            .split()
        )
        require(
            0 < len(ids) <= 32
            and len(set(ids)) == len(ids)
            and all(container_id(i) for i in ids),
            "host_container_set",
        )
        raw = self._run(["docker", "inspect", *sorted(ids)], "inspect")
        values = json.loads(raw)
        require(
            isinstance(values, list) and len(values) == len(ids), "host_inspect_count"
        )
        require({item["Id"] for item in values} == set(ids), "host_inspect_id_set")
        result = {}
        for item in values:
            labels = item["Config"]["Labels"]
            service = labels["com.docker.compose.service"]
            require(service not in result, "host_duplicate_service")
            require(
                labels["com.docker.compose.project"] == self.host["compose_project"],
                "host_project",
            )
            require(
                labels["com.docker.compose.project.working_dir"]
                == str(self.install / "docker"),
                "host_working_directory",
            )
            require(
                container_id(item["Id"]) and image_id(item["Image"]),
                "host_container_identity",
            )
            immutable(item)
            result[service] = item
        require(
            {"api", "web", "nginx", "scheduler"}.issubset(result),
            "host_required_services",
        )
        return result

    def _disabled(self, containers):
        env = containers["api"]["Config"]["Env"]
        pairs = [item.split("=", 1) for item in env]
        values = dict(pairs)
        require(len(values) == len(pairs), "host_duplicate_environment")
        require(
            all(
                values.get(k, "").lower() in {"false", "0", "no", "off"}
                for k in DISABLED_FLAGS
            ),
            "host_channels_enabled",
        )
        require(values.get("DATA_DIR") == "/data", "host_runtime_data_path")
        database = self.install / "api/data/feedback.db"
        require(
            database.is_file() and not database.is_symlink(), "host_policy_database"
        )
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            policies = db.execute(
                "SELECT channel_id, enabled, generation_enabled FROM channel_autoresponse_policy WHERE channel_id IN ('matrix','bisq2') ORDER BY channel_id"
            ).fetchall()
            launch = db.execute(
                "SELECT autonomous_delivery_enabled FROM channel_launch_global WHERE singleton_id=1"
            ).fetchall()
        require(
            len(policies) == 2
            and {r[0] for r in policies} == {"matrix", "bisq2"}
            and all(r[1] == 0 and r[2] in (None, 0) for r in policies)
            and launch == [(0,)],
            "host_generation_enabled",
        )

    def _state(self):
        from .deployment_protocol import validate_phase_receipt

        result = {}
        for path in sorted(self.root.glob("*.intent.json")):
            phase = path.name.removesuffix(".intent.json")
            intent = read_record(path)
            outcome = self.root / f"{phase}.result.json"
            require(outcome.exists(), "host_effect_uncertain")
            value = read_record(outcome)
            require(
                value["intent_sha256"] == digest(encode(intent)), "host_effect_join"
            )
            require(
                value["status"] == "succeeded", "host_effect_requires_reconciliation"
            )
            require(phase in self.plan["phases"], "host_unknown_effect")
            if self.baseline_sha256 is not None:
                require(
                    intent["baseline_sha256"] == self.baseline_sha256,
                    "host_effect_baseline",
                )
                receipt = read_record(self.operation / "receipts" / f"{phase}.json")
                payload = validate_phase_receipt(
                    receipt,
                    self.plan,
                    self.profile,
                    phase,
                    intent["client_intent_sha256"],
                    self.baseline_sha256,
                    approval=self.approval,
                )
                require(payload == value["payload"], "host_effect_receipt_join")
            result[phase] = value["payload"]
        return result

    def _helpers(self):
        require(SCRIPTS.parent == self.candidate, "host_tool_source")
        for name, pin in self.profile["helper_sha256"].items():
            path = self.candidate / name
            require(
                path.is_file()
                and not path.is_symlink()
                and digest(path.read_bytes()) == pin,
                "host_helper_changed",
            )

    def _configuration(self):
        config = json.loads(self._shell("config"))
        env = self.install / "docker/.env"
        require(env.is_file() and not env.is_symlink(), "host_environment_file")
        require(
            self.baseline["compose_sha256"] == digest(encode(config))
            and self.baseline["env_sha256"] == digest(env.read_bytes()),
            "host_configuration_changed",
        )

    def _preserved_data(self, containers):
        """Hash only existing identity/cursor/history records; never export rows."""
        data = self.install / "api/data"
        env = dict(item.split("=", 1) for item in containers["api"]["Config"]["Env"])
        session = env.get("MATRIX_SYNC_SESSION_FILE", "matrix_session.json")
        if session.startswith("/data/"):
            session = session.removeprefix("/data/")
        require(
            bool(re.fullmatch(r"[A-Za-z0-9_.-]+", session))
            and session not in {".", ".."},
            "host_session_path",
        )
        files = {}
        for name in (session, "matrix_polling_state.json"):
            path = data / name
            require(not path.is_symlink(), "host_runtime_symlink")
            if path.exists():
                require(
                    path.is_file() and path.stat().st_size <= 8 * 1024 * 1024,
                    "host_runtime_file",
                )
                files[name] = digest(path.read_bytes())
            else:
                files[name] = None
        database = data / "escalations.db"
        require(
            database.is_file() and not database.is_symlink(), "host_history_database"
        )
        tables = {}
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            names = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for table in (
                "matrix_context_trials",
                "matrix_context_trial_cases",
                "matrix_context_attempts",
            ):
                if table in names:
                    rows = db.execute("SELECT * FROM " + table).fetchmany(10001)
                    require(len(rows) <= 10000, "host_history_bound")
                    tables[table] = {
                        "count": len(rows),
                        "sha256": digest(encode(sorted(rows, key=encode))),
                    }
                else:
                    tables[table] = None
            require("escalations" in names, "host_history_schema")
            cursor = db.execute(
                "SELECT * FROM escalations WHERE channel='matrix' ORDER BY id"
            )
            columns = [column[0] for column in cursor.description]
            require(
                {"id", "channel", "channel_metadata"}.issubset(columns),
                "host_history_schema",
            )
            rows = cursor.fetchmany(10001)
            require(len(rows) <= 10000, "host_history_bound")
            for row in rows:
                raw_metadata = row[columns.index("channel_metadata")]
                try:
                    metadata = json.loads(raw_metadata or "{}")
                except (TypeError, ValueError) as error:
                    raise JournalError("host_context_metadata") from error
                require(isinstance(metadata, dict), "host_context_metadata")
                # ContextReviewStore writes these flat channel_metadata keys.
                # Presence matters: an empty/null scope must not hide in-flight
                # work. Ordinary unrelated Matrix escalations remain allowed.
                if not (
                    metadata.get("response_kind") == "public_context"
                    or any(
                        key in metadata
                        for key in (
                            "context_trial_id",
                            "context_status",
                            "model_call_status",
                        )
                    )
                ):
                    continue
                require(
                    isinstance(metadata.get("context_status"), str)
                    and isinstance(metadata.get("model_call_status"), str)
                    and metadata.get("context_status")
                    in {"deferred", "needs_human", "delivered", "delivery_uncertain"}
                    and metadata.get("model_call_status")
                    in {"not_started", "completed"},
                    "host_context_work_unsettled",
                )
            tables["matrix_cases"] = {
                "count": len(rows),
                "sha256": digest(encode(rows)),
            }
        return {"files": files, "tables": tables}

    def _scheduler_jobs(self, scheduler):
        # docker cp reads the stopped/paused container filesystem; it does not
        # run a process in the held scheduler or recreate it.
        raw = self._run(
            ["docker", "cp", scheduler["Id"] + ":/etc/crontabs/root", "-"],
            "scheduler-cron",
        )
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            members = archive.getmembers()
            require(
                len(members) == 1
                and members[0].isfile()
                and members[0].size <= 1024 * 1024,
                "host_scheduler_cron",
            )
            content = archive.extractfile(members[0]).read()
        return {
            "cron_sha256": digest(content),
            "command_sha256": digest(encode(scheduler["Config"]["Cmd"])),
            "environment_sha256": digest(encode(scheduler["Config"]["Env"])),
        }

    def _prefix(self, phase):
        from .deployment_protocol import validate_phase_receipt

        phases = self.plan["phases"]
        expected = phases[: phases.index(phase)]
        receipts = self.operation / "receipts"
        require(
            {p.stem for p in receipts.glob("*.json")} == set(expected),
            "host_phase_order",
        )
        for prior in expected:
            receipt = read_record(receipts / f"{prior}.json")
            validate_phase_receipt(
                receipt,
                self.plan,
                self.profile,
                prior,
                receipt["intent_sha256"],
                self.baseline_sha256,
                approval=self.approval,
            )

    def _replacement(self, service, current, expected_image):
        """Image content may change; runtime mounts/configuration may not."""
        before = self.baseline["containers"][service]
        require(current["Image"] == expected_image, "host_running_image")
        require(
            sorted(before["Mounts"], key=lambda x: encode(x))
            == sorted(current["Mounts"], key=lambda x: encode(x)),
            "host_replacement_mounts",
        )
        require(
            before["HostConfig"] == current["HostConfig"],
            "host_replacement_host_config",
        )
        old, new = json.loads(json.dumps(before["Config"])), json.loads(
            json.dumps(current["Config"])
        )
        builder_label = "com.docker.compose.image.builder"
        if old["Labels"].get(builder_label) != new["Labels"].get(builder_label):
            # Compose may inherit build metadata from the new immutable image.
            # Join it to this service's completed build, never waive labels from
            # an arbitrary image file or while restoring the original image.
            from .deployment_protocol import validate_phase_receipt

            require(expected_image != before["Image"], "host_builder_image")
            intent = read_record(self.root / "build.intent.json")
            outcome = read_record(self.root / "build.result.json")
            require(
                intent["baseline_sha256"] == self.baseline_sha256
                and outcome["status"] == "succeeded"
                and outcome["intent_sha256"] == digest(encode(intent)),
                "host_builder_build_join",
            )
            payload = validate_phase_receipt(
                read_record(self.operation / "receipts/build.json"),
                self.plan,
                self.profile,
                "build",
                intent["client_intent_sha256"],
                self.baseline_sha256,
                approval=self.approval,
            )
            require(payload == outcome["payload"], "host_builder_receipt_join")
            image_service = "api" if service == "matrix-alert-relay" else service
            require(service in self._consumers(image_service), "host_image_consumer")
            proof = payload["images"][image_service]
            saved = private_json(
                self.root / f"build_{image_service}.image.private.json"
            )
            require(
                proof["image_id"] == expected_image == saved["Id"]
                and proof["image_inspect_sha256"] == digest(encode(saved)),
                "host_builder_image_proof",
            )
            labels = saved.get("Config", {}).get("Labels")
            require(
                isinstance(labels, dict)
                and isinstance(labels.get(builder_label), str)
                and labels[builder_label] == new["Labels"].get(builder_label),
                "host_builder_image_label",
            )
            old["Labels"].pop(builder_label, None)
            new["Labels"].pop(builder_label, None)
        for config, container in ((old, before), (new, current)):
            config.pop("Image", None)
            if config.get("Hostname") == container["Id"][:12]:
                config["Hostname"] = "<docker-generated>"
            require(isinstance(config["Env"], list), "host_replacement_environment")
            environment = {}
            for entry in config["Env"]:
                require(
                    isinstance(entry, str) and "\x00" not in entry,
                    "host_replacement_environment",
                )
                name, separator, value = entry.partition("=")
                require(
                    bool(name) and bool(separator) and name not in environment,
                    "host_replacement_environment",
                )
                environment[name] = value
            if "BUILD_ID" in environment:
                environment["BUILD_ID"] = "<image-build>"
            config["Env"] = environment
            for label in (
                "com.docker.compose.config-hash",
                "com.docker.compose.image",
                "com.docker.compose.project.config_files",
                "com.docker.compose.replace",
            ):
                config["Labels"].pop(label, None)
        require(old == new, "host_replacement_configuration")

    def verify_preservation(self):
        require(self.baseline is not None, "host_preflight_required")
        verify_inherited_lock(self.install, self.lock_fd)
        self._helpers()
        effects = self._state()
        self._source(published="publish_source" in effects)
        self._configuration()
        current = self._inspect()
        self._preserved(current)
        require(
            self._preserved_data(current) == self.baseline["protected_data"],
            "host_protected_data_changed",
        )
        require(
            self._scheduler_jobs(current["scheduler"])
            == self.baseline["scheduler_jobs"],
            "host_scheduler_jobs_changed",
        )
        return {"baseline_sha256": self.baseline_sha256, "preserved": True}

    def _api_ready(self, current, effects, *, reload_nginx=False):
        if "switch_api" in effects:
            expected = effects["build"]["images"]["api"]
            image, build = expected["image_id"], expected["build_id"]
        else:
            image = self.baseline["containers"]["api"]["Image"]
            build = self.baseline["old_build_ids"]["api"]
        self._ready(
            "api",
            current,
            image,
            build,
            reload_nginx=reload_nginx,
            wait_for_route=reload_nginx,
        )

    def verify_backup_resumption(self, phase, intent_sha256, started):
        from .deployment_protocol import effect_guard

        seconds = effect_guard(
            self.plan, self.profile, self.approval, phase, current_time=started
        )
        require(phase.endswith("_backup"), "host_backup_phase")
        require(is_digest(intent_sha256), "host_intent_digest")
        self.effect_until = timestamp(started) + timedelta(seconds=seconds)
        try:
            self._verify_backup_resumption(phase, intent_sha256, started)
        finally:
            self.effect_until = None

    def _verify_backup_resumption(self, phase, intent_sha256, started):
        self.verify_preservation()
        effects = self._state()
        self._prefix(phase)
        require(self.pause_expected, "host_scheduler_not_paused")
        intent = {
            "phase": phase,
            "client_intent_sha256": intent_sha256,
            "baseline_sha256": self.baseline_sha256,
            "started_at": started,
        }
        directory = self.root / "backup-routes"
        directory.mkdir(mode=0o700, exist_ok=True)
        require(
            not directory.is_symlink()
            and stat.S_IMODE(directory.stat().st_mode) == 0o700
            and directory.stat().st_uid == os.geteuid(),
            "host_route_directory",
        )
        intent_path = directory / f"{phase}.intent.json"
        result_path = directory / f"{phase}.result.json"
        exclusive_record(intent_path, intent)
        try:
            # Canonical capture has resumed the same writers, whose endpoints can
            # change without a CID/config change. Refresh the preserved proxy once;
            # only read-only observations may repeat while old workers drain.
            self._api_ready(self._inspect(), effects, reload_nginx=True)
            self.verify_preservation()
        except Exception as error:
            exclusive_record(
                result_path,
                {
                    "intent_sha256": digest(encode(intent)),
                    "status": (
                        "uncertain"
                        if isinstance(error, HostCommandError) and error.uncertain
                        else "failed"
                    ),
                    "finished_at": now(),
                },
            )
            raise
        exclusive_record(
            result_path,
            {
                "intent_sha256": digest(encode(intent)),
                "status": "succeeded",
                "finished_at": now(),
            },
        )

    def verify_completion(self):
        self.verify_preservation()
        effects = self._state()
        require("resume_scheduler" in effects, "host_not_complete")
        current = self._inspect()
        for service in self.plan["services"]:
            built = effects["build"]["images"][service]
            for consumer in self._consumers(service):
                self._ready(
                    consumer,
                    current,
                    built["image_id"],
                    built["build_id"],
                    reload_nginx=False,
                )
        if "api" not in self.plan["services"]:
            self._api_ready(current, effects)
        self._preserved(self._inspect())
        result = {
            "complete": True,
            "fresh_runtime_verified": True,
            "baseline_sha256": self.baseline_sha256,
        }
        path = self.root / "completion.json"
        if path.exists():
            require(read_record(path) == result, "host_completion_changed")
        else:
            exclusive_record(path, result)
        self._marker()
        if self.active_marker.exists():
            self.active_marker.unlink()
            directory = os.open(self.active_marker.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return result | {"active_marker_retired": True}

    def _preserved(self, containers, *, allow_unready=frozenset()):
        require(self.baseline is not None, "host_baseline_missing")
        original = self.baseline["containers"]
        require(set(containers) == set(original), "host_service_set_changed")
        for service, before in original.items():
            expected = self.expected.get(service, before)
            require(
                immutable(containers[service]) == immutable(expected),
                "host_service_identity_changed",
            )
            if service == "nginx":
                require(
                    process_identity(containers[service]) == process_identity(before),
                    "host_nginx_process_changed",
                )
            if service == "scheduler":
                require(
                    process_identity(containers[service]) == process_identity(before),
                    "host_scheduler_process_changed",
                )
                state = containers[service]["State"]
                require(
                    state["Running"]
                    and not state["Restarting"]
                    and state["Paused"] == self.pause_expected,
                    "host_scheduler_state_changed",
                )
            elif service not in {"scheduler-secret-init", "alertmanager-secret-init"}:
                state = containers[service]["State"]
                require(
                    service in allow_unready
                    or state["Running"]
                    and not state["Paused"]
                    and not state["Restarting"],
                    "host_service_not_running",
                )
            else:
                state = containers[service]["State"]
                require(
                    not state["Running"] and state["ExitCode"] == 0,
                    "host_initializer_state",
                )
        self._disabled(containers)

    def _consumers(self, service):
        return self.approval["image_consumers"][service]

    def _consumer_topology(self, config, containers):
        """Only the explicitly approved, existing API relay shares a release."""
        services = config["services"]
        for service in self.plan["services"]:
            expected = [service]
            if service == "api" and "matrix-alert-relay" in services:
                expected.append("matrix-alert-relay")
            require(self._consumers(service) == expected, "host_consumer_scope")
            reference = services[service].get("image")
            require(
                isinstance(reference, str) and bool(reference), "host_consumer_image"
            )
            image = containers[service]["Image"]
            require(
                all(
                    services[name].get("image") == reference
                    and containers[name]["Image"] == image
                    for name in expected
                ),
                "host_consumer_image",
            )
            require(
                {
                    name
                    for name, configuration in services.items()
                    if configuration.get("image") == reference
                    or containers[name]["Image"] == image
                }
                == set(expected),
                "host_unknown_image_consumer",
            )

    def preflight(self):
        verify_inherited_lock(self.install, self.lock_fd)
        self._marker()
        self._helpers()
        effects = self._state()
        self._source(published="publish_source" in effects)
        config = json.loads(self._shell("config"))
        containers = self._inspect()
        require(set(config["services"]) == set(containers), "host_compose_topology")
        self._disabled(containers)
        path = self.root / "baseline.private.json"
        if path.exists():
            self.baseline = private_json(path)
            self.baseline_sha256 = digest(path.read_bytes())
            effects = self._state()
            self.pause_expected = (
                self.baseline["containers"]["scheduler"]["State"]["Paused"]
                if "resume_scheduler" in effects or "pause_scheduler" not in effects
                else True
            )
            require(
                self.baseline["plan_sha256"] == digest(encode(self.plan))
                and self.baseline["profile_sha256"] == digest(encode(self.profile)),
                "host_baseline_join",
            )
            self._consumer_topology(config, self.baseline["containers"])
            for service in self.plan["services"]:
                if "switch_" + service in effects:
                    proofs = effects["switch_" + service]["consumers"]
                    for consumer in self._consumers(service):
                        saved = private_json(
                            self.root / f"switch_{consumer}.container.private.json"
                        )
                        require(
                            saved["Id"] == proofs[consumer]["container_id"]
                            and saved["Image"] == proofs[consumer]["image_id"],
                            "host_consumer_receipt_join",
                        )
                        self._replacement(consumer, saved, proofs[consumer]["image_id"])
                        self.expected[consumer] = saved
            self._preserved(containers)
        else:
            require(not effects, "host_baseline_missing")
            self._consumer_topology(config, containers)
            build_id = self._shell("build-id", self.candidate).decode().strip()
            require(
                bool(re.fullmatch(r"build-[0-9a-f]{7,40}", build_id))
                and self.plan["source"]["candidate_commit"].startswith(
                    build_id.removeprefix("build-")
                ),
                "host_build_id",
            )
            self.pause_expected = containers["scheduler"]["State"]["Paused"]
            self.baseline = {
                "plan_sha256": digest(encode(self.plan)),
                "profile_sha256": digest(encode(self.profile)),
                "containers": containers,
                "compose_sha256": digest(encode(config)),
                "env_sha256": digest((self.install / "docker/.env").read_bytes()),
                "build_id": build_id,
                "old_build_ids": {},
                "protected_data": self._preserved_data(containers),
                "scheduler_jobs": self._scheduler_jobs(containers["scheduler"]),
            }
            for service in sorted(set(self.plan["services"]) | {"api"}):
                if service == "api":
                    values = dict(
                        item.split("=", 1)
                        for item in containers[service]["Config"]["Env"]
                    )
                    previous_build = values.get("BUILD_ID", "")
                else:
                    previous_build = (
                        self._run(
                            [
                                "docker",
                                "exec",
                                containers[service]["Id"],
                                "cat",
                                "/app/.next/BUILD_ID",
                            ],
                            "previous-web-build",
                        )
                        .decode()
                        .strip()
                    )
                require(
                    bool(re.fullmatch(r"build-[0-9a-f]{7,40}", previous_build)),
                    "host_previous_build_id",
                )
                self.baseline["old_build_ids"][service] = previous_build
            self._preserved(containers)
            private_bytes(path, encode(self.baseline))
        require(
            self.baseline["compose_sha256"] == digest(encode(config))
            and self.baseline["env_sha256"]
            == digest((self.install / "docker/.env").read_bytes()),
            "host_configuration_changed",
        )
        self.baseline_sha256 = digest(path.read_bytes())
        require(
            self._preserved_data(containers) == self.baseline["protected_data"]
            and self._scheduler_jobs(containers["scheduler"])
            == self.baseline["scheduler_jobs"],
            "host_preservation_baseline_changed",
        )
        return {
            "baseline_sha256": self.baseline_sha256,
            "build_id": self.baseline["build_id"],
            "services": self.plan["services"],
            "channels_disabled": True,
        }

    def _image(self, reference):
        values = json.loads(
            self._run(["docker", "image", "inspect", reference], "image")
        )
        require(
            isinstance(values, list) and len(values) == 1 and image_id(values[0]["Id"]),
            "host_image_identity",
        )
        return values[0]

    def _overlay(self, name, services):
        path = self.root / f"{name}.compose.json"
        private_bytes(path, encode({"services": services}))
        return path

    def _build(self):
        self._shell(
            "quality",
            self.candidate,
            self.plan["source"]["candidate_commit"],
            self.host["quality_remote"],
            timeout=180,
        )
        images = {}
        for service in self.plan["services"]:
            tag = f"bisq-release-{service}:{self.plan['source']['candidate_commit']}"
            overlay = self._overlay(
                "build_" + service,
                {
                    service: {
                        "image": tag,
                        "pull_policy": "never",
                        "build": {
                            "context": str(self.candidate),
                            "dockerfile": f"docker/{service}/Dockerfile",
                        },
                    }
                },
            )
            self._shell(
                "build",
                overlay,
                service,
                self.baseline["build_id"],
                timeout=self.profile["phase_timeout_seconds"],
            )
            image = self._image(tag)
            # Bind the immutable built image; no tag is used by the switch.
            if service == "api":
                require(
                    "BUILD_ID=" + self.baseline["build_id"] in image["Config"]["Env"],
                    "host_built_build_id",
                )
            else:
                actual = (
                    self._run(
                        [
                            "docker",
                            "run",
                            "--rm",
                            "--network",
                            "none",
                            "--read-only",
                            "--cap-drop",
                            "ALL",
                            "--security-opt",
                            "no-new-privileges",
                            "--name",
                            "bisq-release-build-" + self.operation.name[:24],
                            "--entrypoint",
                            "cat",
                            image["Id"],
                            "/app/.next/BUILD_ID",
                        ],
                        "built-web-id",
                        30,
                    )
                    .decode()
                    .strip()
                )
                require(actual == self.baseline["build_id"], "host_built_build_id")
            images[service] = {
                "image_id": image["Id"],
                "image_inspect_sha256": digest(encode(image)),
                "build_id": self.baseline["build_id"],
            }
            private_bytes(
                self.root / f"build_{service}.image.private.json", encode(image)
            )
        self._preserved(self._inspect())
        return {"images": images, "quality_verified": True, "unrelated_preserved": True}

    def _pause(self):
        before = self.baseline["containers"]["scheduler"]
        paused = before["State"]["Paused"]
        require(
            before["State"]["Running"] and not before["State"]["Restarting"],
            "host_scheduler_state",
        )
        if not paused:
            self._run(["docker", "pause", before["Id"]], "pause", 30)
        current = self._inspect()
        self.pause_expected = True
        self._preserved(current)
        require(
            current["scheduler"]["State"]["Paused"] is True, "host_scheduler_not_paused"
        )
        return {
            "scheduler_id": before["Id"],
            "paused_by_session": not paused,
            "prior_paused": paused,
            "identity_sha256": immutable(before),
        }

    def _ready(
        self,
        service,
        current,
        expected_image,
        expected_build,
        *,
        reload_nginx=True,
        wait_for_route=False,
    ):
        require(current[service]["Image"] == expected_image, "host_running_image")
        self._shell(
            "health",
            service,
            self.host["readiness_timeout_seconds"],
            timeout=self.host["readiness_timeout_seconds"] + 10,
        )
        cid = current[service]["Id"]
        if service == "matrix-alert-relay":
            ready = json.loads(
                self._run(
                    [
                        "docker",
                        "exec",
                        cid,
                        "curl",
                        "-fsS",
                        "--max-time",
                        "10",
                        "http://localhost:8000/ready",
                    ],
                    "relay-ready",
                )
            )
            require(ready.get("status") == "ready", "host_relay_readiness")
            return
        if service == "api":
            ready = json.loads(
                self._run(
                    [
                        "docker",
                        "exec",
                        cid,
                        "curl",
                        "-fsS",
                        "--max-time",
                        "10",
                        "http://localhost:8000/health/ready",
                    ],
                    "ready",
                )
            )
            health = json.loads(
                self._run(
                    [
                        "docker",
                        "exec",
                        cid,
                        "curl",
                        "-fsS",
                        "--max-time",
                        "10",
                        "http://localhost:8000/health",
                    ],
                    "health",
                )
            )
            require(
                ready.get("status") == "ready"
                and health.get("build_id") == expected_build,
                "host_api_readiness",
            )
        else:
            actual = (
                self._run(
                    ["docker", "exec", cid, "cat", "/app/.next/BUILD_ID"],
                    "web-build-id",
                )
                .decode()
                .strip()
            )
            require(actual == expected_build, "host_web_build_id")
        nginx = current["nginx"]["Id"]
        if reload_nginx:
            self._run(["docker", "exec", nginx, "nginx", "-t"], "nginx-config")
            self._run(
                ["docker", "exec", nginx, "nginx", "-s", "reload"], "nginx-reload"
            )
        url = self.host["nginx_url"].rstrip("/")
        if service == "api":
            self._api_route(expected_build, wait=wait_for_route)
        else:
            page = self._run(
                [
                    "curl",
                    "-fsS",
                    "--retry",
                    "0",
                    "--connect-timeout",
                    "5",
                    "--max-time",
                    "15",
                    url + "/login",
                ],
                "route",
            )
            require(expected_build.encode() in page, "host_nginx_web_build")

    def _api_route(self, expected_build, *, wait=False):
        until = time.monotonic() + self.host["readiness_timeout_seconds"]
        while True:
            remaining = until - time.monotonic()
            require(remaining > 0, "host_nginx_api_route_unavailable")
            try:
                routed = json.loads(
                    self._run(
                        [
                            "curl",
                            "-fsS",
                            "--retry",
                            "0",
                            "--connect-timeout",
                            "5",
                            "--max-time",
                            "15",
                            self.host["nginx_url"].rstrip("/") + "/api/health",
                        ],
                        "route",
                        min(15, max(1, int(remaining))),
                    )
                )
                if (
                    isinstance(routed, dict)
                    and routed.get("build_id") == expected_build
                ):
                    return
                require(wait, "host_nginx_api_build")
            except (HostCommandError, json.JSONDecodeError, UnicodeError):
                if not wait:
                    raise
            require(wait, "host_nginx_api_route_unavailable")
            remaining = until - time.monotonic()
            require(remaining > 0, "host_nginx_api_route_unavailable")
            time.sleep(min(0.2, remaining))

    def _switch(self, service, effects):
        require(
            "build" in effects and "pause_scheduler" in effects,
            "host_switch_prerequisites",
        )
        image = effects["build"]["images"][service]
        saved = private_json(self.root / f"build_{service}.image.private.json")
        require(self._image(image["image_id"]) == saved, "host_built_image_changed")
        consumers = self._consumers(service)
        overlay = self._overlay(
            "switch_" + service,
            {
                name: {"image": image["image_id"], "pull_policy": "never"}
                for name in consumers
            },
        )
        self._shell("switch", overlay, *consumers, timeout=120)
        current = self._inspect()
        for name in consumers:
            require(
                current[name]["Id"] != self.baseline["containers"][name]["Id"],
                "host_service_not_replaced",
            )
            self._replacement(name, current[name], image["image_id"])
            self.expected[name] = current[name]
        self._preserved(current)
        for name in consumers:
            self._ready(name, current, image["image_id"], image["build_id"])
        current = self._inspect()
        self._preserved(current)
        for name in consumers:
            private_bytes(
                self.root / f"switch_{name}.container.private.json",
                encode(current[name]),
            )
        return {
            "service": service,
            "consumers": {
                name: {
                    "container_id": current[name]["Id"],
                    "image_id": image["image_id"],
                    "ready": True,
                }
                for name in consumers
            },
            "container_id": current[service]["Id"],
            "image_id": image["image_id"],
            "build_id": image["build_id"],
            "ready": True,
            "nginx_routing_verified": True,
            "unrelated_preserved": True,
        }

    def _smoke(self, kind):
        require(kind in self.approval["smoke_calls"], "host_smoke_not_approved")
        self._shell("smoke", kind, self.host["nginx_url"].rstrip("/"), timeout=150)
        self._preserved(self._inspect())
        return {"kind": kind, "validated": True, "attempts": 1}

    def _publish(self):
        source = self.plan["source"]
        self._source()
        self._git(
            self.install, "merge", "--ff-only", "--no-edit", source["candidate_commit"]
        )
        self._source(published=True)
        self._preserved(self._inspect())
        return {
            "candidate_commit": source["candidate_commit"],
            "candidate_tree": source["candidate_tree"],
            "previous_commit": source["previous_commit"],
            "source_clean": True,
            "unrelated_preserved": True,
        }

    def restore_availability(self, phase: str):
        """Restore only a proven failed switch, never resume the failed rollout.

        The dispatcher must call this explicitly while this lock owner remains
        alive. A lost/ambiguous switch or any started smoke requires inspection.
        """
        from .deployment_protocol import effect_guard

        require(
            phase in {"switch_" + service for service in self.plan["services"]},
            "host_recovery_phase",
        )
        seconds = effect_guard(self.plan, self.profile, self.approval, phase)
        self.effect_until = timestamp(now()) + timedelta(seconds=seconds)
        require(
            self.approval["data_compatible_rollback"] is True, "host_recovery_authority"
        )
        verify_inherited_lock(self.install, self.lock_fd)
        self._helpers()
        self._source()
        self._configuration()
        self._prefix(phase)
        intent = read_record(self.root / f"{phase}.intent.json")
        result_path = self.root / f"{phase}.result.json"
        failed = read_record(result_path)
        require(
            failed["status"] == "failed"
            and failed["intent_sha256"] == digest(encode(intent))
            and intent["baseline_sha256"] == self.baseline_sha256,
            "host_recovery_not_known_failure",
        )
        require(
            not any(self.root.glob("smoke_*.intent.json")), "host_recovery_after_smoke"
        )
        service = phase.removeprefix("switch_")
        baseline = cast(dict, self.baseline)
        consumers = self._consumers(service)
        candidate = private_json(self.root / f"build_{service}.image.private.json")
        # The prior build receipt was validated by _prefix; bind its immutable
        # image proof even when no builder-label variance needs normalization.
        built = read_record(self.operation / "receipts/build.json")["payload"][
            "images"
        ][service]
        require(
            candidate["Id"] == built["image_id"]
            and digest(encode(candidate)) == built["image_inspect_sha256"],
            "host_recovery_candidate_image",
        )
        current = self._inspect()
        for name in consumers:
            before = baseline["containers"][name]
            require(
                current[name]["Image"] in {before["Image"], candidate["Id"]},
                "host_recovery_topology",
            )
            self._replacement(name, current[name], current[name]["Image"])
            self.expected[name] = current[name]
            original_image = self._image(before["Image"])
            require(
                original_image["Id"] == before["Image"], "host_recovery_original_image"
            )
        self._preserved(current, allow_unready=set(consumers))
        recovery = {
            "phase": phase,
            "failed_result_sha256": digest(result_path.read_bytes()),
            "started_at": now(),
        }
        exclusive_record(self.root / "availability-recovery.intent.json", recovery)
        try:
            if any(
                current[name]["Image"] != baseline["containers"][name]["Image"]
                or not current[name]["State"]["Running"]
                for name in consumers
            ):
                overlay = self._overlay(
                    "availability-recovery",
                    {
                        name: {
                            "image": baseline["containers"][name]["Image"],
                            "pull_policy": "never",
                        }
                        for name in consumers
                    },
                )
                self._shell("switch", overlay, *consumers, timeout=120)
            current = self._inspect()
            for name in consumers:
                self._replacement(
                    name, current[name], baseline["containers"][name]["Image"]
                )
                self.expected[name] = current[name]
            for name in consumers:
                self._ready(
                    name,
                    current,
                    baseline["containers"][name]["Image"],
                    baseline["old_build_ids"][service],
                )
            self._preserved(self._inspect())
        except Exception as error:
            exclusive_record(
                self.root / "availability-recovery.result.json",
                {
                    "intent_sha256": digest(encode(recovery)),
                    "status": (
                        "uncertain"
                        if isinstance(error, HostCommandError) and error.uncertain
                        else "failed"
                    ),
                    "finished_at": now(),
                },
            )
            raise
        result = {
            "intent_sha256": digest(encode(recovery)),
            "status": "availability_restored",
            "consumers": {
                name: {
                    "container_id": current[name]["Id"],
                    "image_id": current[name]["Image"],
                    "ready": True,
                }
                for name in consumers
            },
            "rollout_complete": False,
            "failed_phase_preserved": True,
            "scheduler_remains_held": True,
            "finished_at": now(),
        }
        exclusive_record(self.root / "availability-recovery.result.json", result)
        return result

    def _resume(self, effects):
        require(
            "publish_source" in effects and "pause_scheduler" in effects,
            "host_resume_prerequisites",
        )
        before = self.baseline["containers"]["scheduler"]
        current = self._inspect()
        self._preserved(current)
        require(
            current["scheduler"]["State"]["Paused"] is True, "host_scheduler_not_paused"
        )
        self._api_ready(current, effects)
        if effects["pause_scheduler"]["paused_by_session"]:
            self._run(["docker", "unpause", before["Id"]], "unpause", 30)
        current = self._inspect()
        self.pause_expected = before["State"]["Paused"]
        self._preserved(current)
        require(
            current["scheduler"]["State"]["Paused"] == before["State"]["Paused"],
            "host_scheduler_pause_changed",
        )
        require(
            self._preserved_data(current) == self.baseline["protected_data"],
            "host_protected_data_changed",
        )
        require(
            self._scheduler_jobs(current["scheduler"])
            == self.baseline["scheduler_jobs"],
            "host_scheduler_jobs_changed",
        )
        return {
            "scheduler_id": before["Id"],
            "original_process_preserved": True,
            "original_pause_restored": True,
            "job_config_preserved": True,
            "unrelated_preserved": True,
        }

    def effect(self, phase: str, intent_sha256: str) -> dict:
        from .deployment_protocol import effect_guard

        seconds = effect_guard(self.plan, self.profile, self.approval, phase)
        self.effect_until = timestamp(now()) + timedelta(seconds=seconds)
        require(is_digest(intent_sha256), "host_intent_digest")
        require(self.baseline is not None, "host_preflight_required")
        verify_inherited_lock(self.install, self.lock_fd)
        effects = self._state()
        self._prefix(phase)
        require(phase not in effects, "host_phase_repeated")
        self.verify_preservation()
        self._marker(create=True)
        handlers: dict[str, Callable[[], dict]] = {
            "build": self._build,
            "pause_scheduler": self._pause,
            "publish_source": self._publish,
            "resume_scheduler": lambda: self._resume(effects),
            "smoke_standard": lambda: self._smoke("standard"),
            "smoke_live_mcp": lambda: self._smoke("live_mcp"),
        }
        for service in self.plan["services"]:
            handlers["switch_" + service] = partial(self._switch, service, effects)
        require(phase in handlers, "host_phase_unsupported")
        intent = {
            "phase": phase,
            "client_intent_sha256": intent_sha256,
            "baseline_sha256": self.baseline_sha256,
            "started_at": now(),
        }
        exclusive_record(self.root / f"{phase}.intent.json", intent)
        try:
            payload = handlers[phase]()
        except Exception as error:
            uncertain = isinstance(error, HostCommandError) and (
                error.uncertain or phase.startswith("smoke_")
            )
            exclusive_record(
                self.root / f"{phase}.result.json",
                {
                    "intent_sha256": digest(encode(intent)),
                    "status": "uncertain" if uncertain else "failed",
                    "code": (
                        str(error)
                        if isinstance(error, JournalError)
                        else "host_validation_failed"
                    ),
                    "finished_at": now(),
                },
            )
            raise
        exclusive_record(
            self.root / f"{phase}.result.json",
            {
                "intent_sha256": digest(encode(intent)),
                "status": "succeeded",
                "payload": payload,
                "finished_at": now(),
            },
        )
        self.effect_until = None
        return payload

    def status(self):
        phases = {}
        for path in self.root.glob("*.intent.json"):
            phase = path.name.removesuffix(".intent.json")
            result = self.root / f"{phase}.result.json"
            phases[phase] = (
                read_record(result)["status"] if result.exists() else "uncertain"
            )
        return {
            "baseline_sha256": self.baseline_sha256,
            "phases": phases,
            "complete": phases.get("resume_scheduler") == "succeeded",
        }

    def close(self):
        # The stdio owner releases its own descriptor on process exit. Never
        # unpause a scheduler or compensate an ambiguous effect on disconnect.
        return None

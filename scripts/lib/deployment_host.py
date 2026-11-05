"""Selective, source-only host effects under the canonical lifecycle lock.

The stdio owner supplies phase ordering/approval and remains alive while local
recovery is verified. This backend stores private observations and exclusive
effect records; reconnecting never supplies a new baseline or retries an intent.
"""

from __future__ import annotations

import io
import json
import math
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
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Callable, cast
from urllib.parse import quote

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
            plan["schema"]
            in {
                "deployment-plan-v2",
                "deployment-plan-v3",
                "deployment-plan-v4",
                "deployment-plan-v5",
            },
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
        from deploy_release import (
            changed_paths,
            classify_services,
            monitoring_hashes,
            preserved_heap_hashes,
            python_runner_hashes,
            tooling_hashes,
        )

        from .deployment_protocol import DEPLOYMENT_TOOLING

        source = self.plan["source"]
        heap = bool(self.plan.get("preserved_heap_sha256"))
        monitoring = self.plan["schema"] == "deployment-plan-v5"
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
            if heap and path == self.install and not published:
                self._heap_worktree()
            else:
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
        tooling = self.plan["schema"] in {
            "deployment-plan-v3",
            "deployment-plan-v4",
            "deployment-plan-v5",
        }
        require(
            classify_services(
                paths,
                include_deployment_tooling=tooling,
                preserve_bisq2_heap_repair=heap,
                include_retention_monitoring=monitoring,
                include_python_runner_pins=bool(self.plan.get("python_runner_sha256")),
            )
            == self.plan["services"],
            "host_source_scope",
        )
        if tooling:
            actual_tooling = (
                tooling_hashes(self.candidate, source["candidate_commit"], paths)
                if self.plan["tooling_sha256"]
                or any(p in DEPLOYMENT_TOOLING for p in paths)
                else {}
            )
            require(
                actual_tooling == self.plan["tooling_sha256"],
                "host_source_tooling",
            )
            require(
                self.approval["tooling_sha256"] == self.plan["tooling_sha256"],
                "approval_tooling",
            )
        if heap:
            require(
                preserved_heap_hashes(
                    self.candidate,
                    source["previous_commit"],
                    source["candidate_commit"],
                    paths,
                )
                == self.plan["preserved_heap_sha256"]
                == self.approval["preserved_heap_sha256"],
                "host_preserved_heap",
            )
        if monitoring:
            require(
                monitoring_hashes(self.candidate, source["candidate_commit"], paths)
                == self.plan["monitoring_sha256"]
                == self.approval["monitoring_sha256"],
                "host_monitoring_source",
            )
            runner_pins = (
                python_runner_hashes(
                    self.candidate,
                    source["previous_commit"],
                    source["candidate_commit"],
                    paths,
                )
                if self.plan["python_runner_sha256"]
                else {}
            )
            require(
                runner_pins
                == self.plan["python_runner_sha256"]
                == self.approval["python_runner_sha256"],
                "host_python_runner_source",
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

    def _heap_worktree(self):
        """Only one unstaged candidate-identical Compose repair may pre-exist."""
        name = "docker/docker-compose.yml"
        path = self.install / name
        require(
            self._git(
                self.install,
                "status",
                "--porcelain=v1",
                "--untracked-files=normal",
                "-z",
            )
            == "M " + name + "\0"
            and not self._git(self.install, "diff", "--cached", "--name-only"),
            "host_heap_source_dirty",
        )
        require(
            not any(p.is_symlink() for p in (path, *path.parents))
            and path.is_file()
            and path.stat().st_size <= 1024 * 1024
            and stat.S_IMODE(path.stat().st_mode) == 0o644
            and path.stat().st_nlink == 1
            and digest(path.read_bytes()) == self.plan["preserved_heap_sha256"][name],
            "host_heap_file_changed",
        )

    def _heap_runtime(self, containers):
        if not self.plan.get("preserved_heap_sha256"):
            return
        require("bisq2-api" in containers, "host_heap_node_missing")
        node = containers["bisq2-api"]
        pairs = [item.split("=", 1) for item in node["Config"]["Env"]]
        require(all(len(p) == 2 for p in pairs), "host_heap_environment")
        env = dict(pairs)
        require(
            len(env) == len(pairs)
            and env.get("JAVA_OPTS") == "-Xmx2g -XX:+ExitOnOutOfMemoryError"
            and node["HostConfig"]["Memory"] == 4294967296
            and node["HostConfig"]["RestartPolicy"]["Name"] == "always",
            "host_heap_runtime",
        )

    def _container_file(self, container, filename, label):
        raw = self._run(["docker", "cp", container["Id"] + ":" + filename, "-"], label)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            members = archive.getmembers()
            require(
                len(members) == 1
                and members[0].isfile()
                and members[0].size <= 1024 * 1024,
                "host_monitoring_file",
            )
            return archive.extractfile(members[0]).read()

    def _monitoring_file(self, name):
        path = self.install / name
        require(
            not any(p.is_symlink() for p in (path, *path.parents)),
            "host_monitoring_symlink",
        )
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_size <= 1024 * 1024,
                "host_monitoring_file",
            )
            raw = stream.read()
        return {
            "inode": info.st_ino,
            "device": info.st_dev,
            "mode": stat.S_IMODE(info.st_mode),
            "uid": info.st_uid,
            "gid": info.st_gid,
            "sha256": digest(raw),
        }

    @staticmethod
    def _metric(raw, name):
        # Exactly one unlabeled local metric. Neither missing nor NaN is success.
        values = re.findall(
            rb"^" + re.escape(name.encode()) + rb" ([^\s]+)$", raw, re.MULTILINE
        )
        require(len(values) == 1, "host_monitoring_metric")
        value = float(values[0])
        require(math.isfinite(value) and value >= 0, "host_monitoring_metric")
        return value

    def _monitoring_reload_state(self, prometheus):
        raw = self._run(
            [
                "docker",
                "exec",
                prometheus["Id"],
                "/bin/wget",
                "-qO-",
                "http://127.0.0.1:9090/metrics",
            ],
            "monitoring-reload-state",
        )
        return {
            "success": self._metric(raw, "prometheus_config_last_reload_successful"),
            "timestamp": self._metric(
                raw, "prometheus_config_last_reload_success_timestamp_seconds"
            ),
        }

    def _monitoring_expected_rules(self, prometheus, raw):
        # This capability intentionally accepts the checked-in indentation and
        # plain/literal expressions only; it is not a permissive YAML parser.
        text = raw.decode("utf-8")
        blocks = re.split(r"(?m)^      - (alert|record): ([A-Za-z0-9_:]+)\n", text)
        wanted = {
            "privacy_retention:verified_scheduler_hold",
            "PrivacyRetentionHeld",
            "PrivacyRetentionHoldInvalid",
            "PrivacyRetentionMetricsMissing",
            "PrivacyRetentionJobStale",
            "PrivacyRetentionLogMetricsMissing",
            "PrivacyRetentionLogJobStale",
            "PrivacyRetentionWindowExceeded",
        }
        expected = {}
        for index in range(1, len(blocks), 3):
            kind, name, body = blocks[index : index + 3]
            if name not in wanted:
                continue
            require(name not in expected, "host_monitoring_rule_duplicate")
            match = re.search(r"(?m)^        expr: ([^\n]+)\n", body)
            require(match is not None, "host_monitoring_rule_expression")
            expression = match.group(1)
            if expression == "|":
                lines = []
                for line in body[match.end() :].splitlines():
                    if not line.startswith("          "):
                        break
                    lines.append(line[10:])
                expression = "\n".join(lines)
            require(
                bool(expression) and expression not in {">", "|-", "|+"},
                "host_monitoring_rule_expression",
            )
            formatted = (
                self._run(
                    [
                        "docker",
                        "exec",
                        prometheus["Id"],
                        "/bin/promtool",
                        "--experimental",
                        "promql",
                        "format",
                        expression,
                    ],
                    "monitoring-rule-format",
                )
                .decode()
                .strip()
            )
            expected[name] = {
                "query": formatted,
                "type": "recording" if kind == "record" else "alerting",
            }
        require(set(expected) == wanted, "host_monitoring_rule_set")
        return expected

    def _monitoring_loaded_rules(self, prometheus):
        raw = self._run(
            [
                "docker",
                "exec",
                prometheus["Id"],
                "/bin/wget",
                "-qO-",
                "http://127.0.0.1:9090/api/v1/rules",
            ],
            "monitoring-loaded-rules",
        )
        response = json.loads(raw)
        require(response.get("status") == "success", "host_monitoring_loaded_rules")
        groups = response.get("data", {}).get("groups", [])
        require(
            isinstance(groups, list) and 1 <= len(groups) <= 100,
            "host_monitoring_loaded_rules",
        )
        rules = [rule for group in groups for rule in group.get("rules", [])]
        require(len(rules) <= 1000, "host_monitoring_loaded_rules")
        wanted = {
            "privacy_retention:verified_scheduler_hold",
            "PrivacyRetentionHeld",
            "PrivacyRetentionHoldInvalid",
            "PrivacyRetentionMetricsMissing",
            "PrivacyRetentionJobStale",
            "PrivacyRetentionLogMetricsMissing",
            "PrivacyRetentionLogJobStale",
            "PrivacyRetentionWindowExceeded",
        }
        selected = [rule for rule in rules if rule.get("name") in wanted]
        require(
            len(selected) == len(wanted) and {r["name"] for r in selected} == wanted,
            "host_monitoring_loaded_rules",
        )
        require(
            all(r.get("health") in {"ok", "unknown"} for r in selected),
            "host_monitoring_loaded_rules",
        )
        if any(r.get("health") != "ok" for r in selected):
            return None
        for rule in selected:
            name = rule["name"]
            if name == "privacy_retention:verified_scheduler_hold":
                require(rule.get("type") == "recording", "host_monitoring_loaded_rules")
            else:
                require(
                    rule.get("type") == "alerting"
                    and rule.get("labels", {}).get("severity")
                    == ("warning" if name == "PrivacyRetentionHeld" else "critical"),
                    "host_monitoring_loaded_rules",
                )
            query = rule.get("query", "")
            require(
                isinstance(query, str) and bool(query), "host_monitoring_loaded_rules"
            )
            formatted = (
                self._run(
                    [
                        "docker",
                        "exec",
                        prometheus["Id"],
                        "/bin/promtool",
                        "--experimental",
                        "promql",
                        "format",
                        query,
                    ],
                    "monitoring-loaded-rule-format",
                )
                .decode()
                .strip()
            )
            require(
                {"query": formatted, "type": rule["type"]}
                == self.baseline["monitoring"]["expected_rules"][name],
                "host_monitoring_loaded_expression",
            )
            if name in {
                "PrivacyRetentionMetricsMissing",
                "PrivacyRetentionJobStale",
                "PrivacyRetentionLogMetricsMissing",
                "PrivacyRetentionLogJobStale",
            }:
                require(
                    "unless on () privacy_retention:verified_scheduler_hold" in query,
                    "host_monitoring_loaded_rules",
                )
            if name == "PrivacyRetentionWindowExceeded":
                require(
                    "privacy_retention:verified_scheduler_hold" not in query,
                    "host_monitoring_loaded_rules",
                )
        return digest(
            encode(
                [
                    {k: r.get(k) for k in ("name", "type", "query", "labels")}
                    for r in sorted(selected, key=lambda r: r["name"])
                ]
            )
        )

    def _monitoring_query(self, prometheus, expression):
        url = "http://127.0.0.1:9090/api/v1/query?query=" + quote(expression, safe="")
        value = json.loads(
            self._run(
                ["docker", "exec", prometheus["Id"], "/bin/wget", "-qO-", url],
                "monitoring-query",
            )
        )
        require(
            value.get("status") == "success"
            and value.get("data", {}).get("resultType") == "vector",
            "host_monitoring_query",
        )
        rows = value["data"].get("result")
        require(isinstance(rows, list) and len(rows) <= 1, "host_monitoring_query")
        if not rows:
            return None
        pair = rows[0].get("value")
        require(isinstance(pair, list) and len(pair) == 2, "host_monitoring_query")
        timestamp_value, metric_value = map(float, pair)
        require(
            math.isfinite(timestamp_value)
            and math.isfinite(metric_value)
            and timestamp_value >= 0,
            "host_monitoring_query",
        )
        return {"timestamp": timestamp_value, "value": metric_value}

    def _monitoring_scraped_hold(self, prometheus, heartbeat):
        observed = self._monitoring_query(
            prometheus,
            'scheduler_retention_hold_observed_timestamp_seconds{job="node-exporter"}',
        )
        hold = self._monitoring_query(
            prometheus, "privacy_retention:verified_scheduler_hold"
        )
        hold_sample = self._monitoring_query(
            prometheus, "timestamp(privacy_retention:verified_scheduler_hold)"
        )
        if (
            observed is None
            or hold is None
            or hold_sample is None
            or observed["value"] < heartbeat
            or not 0 <= time.time() - observed["value"] < 180
            or hold["value"] != 1
            or not heartbeat <= hold_sample["value"] <= time.time()
        ):
            return None
        # Later scrapes must not invalidate a correctly evaluated recording.
        # Prove the sample that was available at that recording's actual time,
        # rather than compare its timestamp with the most recent scrape.
        at = format(hold_sample["value"], ".6f")
        selector = (
            'scheduler_retention_hold_observed_timestamp_seconds{job="node-exporter"}'
            + " @ "
            + at
        )
        consumed = self._monitoring_query(prometheus, selector)
        consumed_sample = self._monitoring_query(
            prometheus, "timestamp(" + selector + ")"
        )
        if (
            consumed is None
            or consumed_sample is None
            or not heartbeat <= consumed["value"] <= hold_sample["value"]
            or not heartbeat <= consumed_sample["value"] <= hold_sample["value"]
        ):
            return None
        raw = self._run(
            [
                "docker",
                "exec",
                prometheus["Id"],
                "/bin/wget",
                "-qO-",
                "http://127.0.0.1:9090/api/v1/alerts",
            ],
            "monitoring-alert-state",
        )
        value = json.loads(raw)
        require(value.get("status") == "success", "host_monitoring_alerts")
        alerts = value.get("data", {}).get("alerts")
        require(
            isinstance(alerts, list) and len(alerts) <= 1000, "host_monitoring_alerts"
        )
        targets = {
            "PrivacyRetentionMetricsMissing",
            "PrivacyRetentionJobStale",
            "PrivacyRetentionLogMetricsMissing",
            "PrivacyRetentionLogJobStale",
        }
        if any(alert.get("labels", {}).get("alertname") in targets for alert in alerts):
            return None
        return {
            "scraped_heartbeat_timestamp": observed["value"],
            "hold_recording_sample_timestamp": hold_sample["value"],
            "consumed_heartbeat_timestamp": consumed["value"],
            "consumed_scrape_timestamp": consumed_sample["value"],
            "held_job_stale_alerts_inactive": True,
        }

    def _monitoring_mounts(self, containers):
        expected = [
            (
                "scheduler",
                "docker/scripts/scheduler-heartbeat.sh",
                "/scripts/scheduler-heartbeat.sh",
            ),
            ("prometheus", "docker/prometheus", "/etc/prometheus"),
        ]
        for service, name, target in expected:
            require(service in containers, "host_monitoring_service")
            mounts = containers[service]["Mounts"]
            matches = [m for m in mounts if m.get("Destination") == target]
            require(
                len(matches) == 1
                and matches[0].get("Type") == "bind"
                and matches[0].get("Source") == str(self.install / name),
                "host_monitoring_mount",
            )
        for service, name, target in [
            (
                "scheduler",
                "docker/scripts/scheduler-heartbeat.sh",
                "/scripts/scheduler-heartbeat.sh",
            ),
            (
                "prometheus",
                "docker/prometheus/alert_rules.yml",
                "/etc/prometheus/alert_rules.yml",
            ),
        ]:
            actual = self._container_file(
                containers[service], target, "monitoring-mounted-file"
            )
            require(
                digest(actual) == self._monitoring_file(name)["sha256"],
                "host_monitoring_mount_bytes",
            )

    def _monitoring_baseline(self, containers):
        require(
            not containers["scheduler"]["State"]["Paused"],
            "host_monitoring_originally_paused",
        )
        self._monitoring_mounts(containers)
        script = self.candidate / "docker/scripts/scheduler-heartbeat.sh"
        rules = self.candidate / "docker/prometheus/alert_rules.yml"
        self._run(["bash", "-n", str(script)], "monitoring-shell-check")
        # No-argument promtool check rules consumes stdin without writing files.
        self._run(
            [
                "docker",
                "exec",
                "-i",
                containers["prometheus"]["Id"],
                "/bin/promtool",
                "check",
                "rules",
            ],
            "monitoring-rules-check",
            input_bytes=rules.read_bytes(),
        )
        reload_state = self._monitoring_reload_state(containers["prometheus"])
        require(
            reload_state["success"] == 1 and reload_state["timestamp"] > 0,
            "host_monitoring_reload_state",
        )
        metrics = self._container_file(
            containers["scheduler"],
            "/var/lib/node_exporter/textfile_collector/scheduler-heartbeat.prom",
            "monitoring-heartbeat-before",
        )
        heartbeat = self._metric(metrics, "scheduler_heartbeat_timestamp_seconds")
        require(0 <= time.time() - heartbeat < 180, "host_monitoring_heartbeat_stale")
        return {
            "heartbeat_file": self._monitoring_file(
                "docker/scripts/scheduler-heartbeat.sh"
            ),
            "reload_timestamp": reload_state["timestamp"],
            "heartbeat_timestamp": heartbeat,
            "expected_rules": self._monitoring_expected_rules(
                containers["prometheus"], rules.read_bytes()
            ),
        }

    def _monitoring_preserved(self, containers):
        """Require the latest proved process and the original single-file bind identity."""
        if self.plan["schema"] != "deployment-plan-v5":
            return
        require(
            process_identity(containers["prometheus"])
            == self._monitoring_expected_state()["process"],
            "host_monitoring_process_changed",
        )
        before = self.baseline["monitoring"]["heartbeat_file"]
        current = self._monitoring_file("docker/scripts/scheduler-heartbeat.sh")
        require(
            all(
                current[k] == before[k]
                for k in ("inode", "device", "mode", "uid", "gid")
            ),
            "host_monitoring_inode_changed",
        )
        self._monitoring_mounts(containers)

    @staticmethod
    def _process_started_ns(process):
        """Docker's UTC nanosecond timestamp, without float clock rounding."""
        require(
            set(process) == {"pid", "started_at", "restart_count"}
            and type(process["pid"]) is int
            and process["pid"] > 0
            and type(process["restart_count"]) is int
            and process["restart_count"] >= 0,
            "host_monitoring_backup_process",
        )
        match = re.fullmatch(
            r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?(?:Z|\+00:00)",
            process["started_at"],
        )
        require(match is not None, "host_monitoring_backup_process")
        value = datetime.fromisoformat(match[1] + "+00:00")
        epoch = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
        return (epoch.days * 86400 + epoch.seconds) * 10**9 + int(
            (match[2] or "").ljust(9, "0")
        )

    def _monitoring_backup_proof(self, phase, intent_sha256, canonical_receipt_sha256):
        """Join accepted capture bytes and owner clocks; mtimes detect tampering only."""
        require(
            phase in {"prechange_backup", "postchange_backup"}
            and is_digest(intent_sha256)
            and is_digest(canonical_receipt_sha256),
            "host_monitoring_backup_binding",
        )
        directory = self.operation / "recovery" / phase

        def saved(name):
            path = directory / name
            before = path.lstat()
            value = read_record(path)
            raw = path.read_bytes()
            after = path.lstat()
            require(
                not any(p.is_symlink() for p in (path, *path.parents))
                and (
                    before.st_dev,
                    before.st_ino,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                )
                == (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns),
                "host_monitoring_backup_evidence_changed",
            )
            return value, digest(raw), before.st_mtime_ns

        capture, capture_sha, capture_mtime = saved("capture-intent.json")
        require(
            capture
            == {
                "plan_sha256": digest(encode(self.plan)),
                "profile_sha256": digest(encode(self.profile)),
                "phase": phase,
                "intent_sha256": intent_sha256,
                "deadline": self.approval["deadline"],
            },
            "host_monitoring_backup_binding",
        )
        receipt, receipt_sha, receipt_mtime = saved("canonical-backup.json")
        require(
            receipt_sha == canonical_receipt_sha256,
            "host_monitoring_capture_receipt_changed",
        )
        require(
            set(receipt)
            == {
                "schema",
                "ciphertext_name",
                "ciphertext_sha256",
                "ciphertext_bytes",
                "destination_kind",
                "writers_resumed",
                "scratch_cleanup_verified",
            }
            and receipt["schema"] == "canonical-backup-v1"
            and receipt["destination_kind"] == "same_host_encrypted_export"
            and receipt["writers_resumed"] is True
            and receipt["scratch_cleanup_verified"] is True
            and is_digest(receipt["ciphertext_sha256"])
            and type(receipt["ciphertext_bytes"]) is int
            and receipt["ciphertext_bytes"] > 0
            and isinstance(receipt["ciphertext_name"], str)
            and re.fullmatch(
                r"bisq-support-backup-[A-Za-z0-9_.-]+\.tar\.gz\.(age|gpg)",
                receipt["ciphertext_name"],
            ),
            "host_monitoring_backup_receipt",
        )
        start, start_sha, start_mtime = saved("monitoring-capture.intent.json")
        completion, completion_sha, completion_mtime = saved(
            "monitoring-capture.result.json"
        )
        require(
            start
            == {
                "schema": "deployment-monitoring-capture-intent-v1",
                "binding": capture,
            },
            "host_monitoring_capture_window_binding",
        )
        require(
            set(completion)
            == {
                "schema",
                "intent_sha256",
                "canonical_backup_receipt_sha256",
                "began",
                "finished",
            }
            and completion["schema"] == "deployment-monitoring-capture-result-v1"
            and completion["intent_sha256"] == digest(encode(start))
            and completion["canonical_backup_receipt_sha256"]
            == canonical_receipt_sha256,
            "host_monitoring_capture_window_binding",
        )
        began_ns, finished_ns = self._monitoring_capture_window(completion)
        return {
            "capture_intent_sha256": capture_sha,
            "canonical_backup_sha256": receipt_sha,
            "monitoring_capture_intent_sha256": start_sha,
            "monitoring_capture_result_sha256": completion_sha,
            "saved_mtimes_ns": [
                capture_mtime,
                receipt_mtime,
                start_mtime,
                completion_mtime,
            ],
            "capture_started_ns": began_ns,
            "capture_finished_ns": finished_ns,
        }

    @staticmethod
    def _monitoring_capture_window(completion):
        """Reject clock steps using the measured sampling envelope, not tolerance."""
        began, finished = completion["began"], completion["finished"]
        for sample in (began, finished):
            require(
                set(sample) == {"wall_before_ns", "monotonic_ns", "wall_after_ns"}
                and all(type(v) is int and v > 0 for v in sample.values())
                and sample["wall_before_ns"] <= sample["wall_after_ns"],
                "host_monitoring_capture_clock",
            )
        elapsed = finished["monotonic_ns"] - began["monotonic_ns"]
        lower = finished["wall_before_ns"] - began["wall_after_ns"]
        upper = finished["wall_after_ns"] - began["wall_before_ns"]
        require(0 < lower <= elapsed <= upper, "host_monitoring_capture_clock")
        return began["wall_after_ns"], finished["wall_before_ns"]

    def _monitoring_expected_state(self):
        """Revalidate the private checkpoint chain against its original capture proofs."""
        expected = process_identity(self.baseline["containers"]["prometheus"])
        reload_timestamp = self.baseline["monitoring"]["reload_timestamp"]
        directory = self.root / "backup-processes"
        if not directory.exists():
            require(not directory.is_symlink(), "host_monitoring_backup_directory")
            return {"process": expected, "reload_timestamp": reload_timestamp}
        info = directory.lstat()
        require(
            stat.S_ISDIR(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o700
            and info.st_uid == os.geteuid(),
            "host_monitoring_backup_directory",
        )
        phases = ("prechange_backup", "postchange_backup")
        present = {p.name for p in directory.iterdir()}
        require(
            present <= {phase + ".json" for phase in phases}
            and (
                "postchange_backup.json" not in present
                or "prechange_backup.json" in present
            ),
            "host_monitoring_backup_order",
        )
        for phase in phases:
            if phase + ".json" not in present:
                continue
            record = read_record(directory / (phase + ".json"))
            require(
                set(record)
                == {
                    "schema",
                    "phase",
                    "plan_sha256",
                    "profile_sha256",
                    "baseline_sha256",
                    "client_intent_sha256",
                    "proof",
                    "before",
                    "after",
                    "container_identity_sha256",
                    "reload_state",
                    "previous_reload_timestamp",
                }
                and record["schema"] == "deployment-backup-process-v1"
                and record["phase"] == phase
                and record["plan_sha256"] == digest(encode(self.plan))
                and record["profile_sha256"] == digest(encode(self.profile))
                and record["baseline_sha256"] == self.baseline_sha256
                and record["before"] == expected
                and record["previous_reload_timestamp"] == reload_timestamp
                and record["container_identity_sha256"]
                == immutable(self.baseline["containers"]["prometheus"]),
                "host_monitoring_backup_checkpoint",
            )
            proof = self._monitoring_backup_proof(
                phase,
                record["client_intent_sha256"],
                record["proof"]["canonical_backup_sha256"],
            )
            require(record["proof"] == proof, "host_monitoring_backup_evidence_changed")
            began = self._process_started_ns(record["after"])
            require(
                proof["capture_started_ns"] <= began <= proof["capture_finished_ns"]
                and began > self._process_started_ns(expected)
                and record["after"]["restart_count"] == 0,
                "host_monitoring_backup_process",
            )
            self._monitoring_backup_reload(record["reload_state"], began, proof)
            expected = record["after"]
            reload_timestamp = record["reload_state"]["timestamp"]
        return {"process": expected, "reload_timestamp": reload_timestamp}

    @staticmethod
    def _monitoring_backup_reload(state, started_ns, proof):
        """Require the successful startup load inside the accepted capture window."""
        require(
            set(state) == {"success", "timestamp"}
            and state["success"] == 1
            and type(state["timestamp"]) in (float, int)
            and math.isfinite(state["timestamp"]),
            "host_monitoring_backup_reload",
        )
        reloaded_ns = int(Decimal(str(state["timestamp"])) * 10**9)
        require(
            started_ns <= reloaded_ns <= proof["capture_finished_ns"],
            "host_monitoring_backup_reload",
        )

    def _monitoring_accept_backup_process(
        self, phase, intent_sha256, canonical_receipt_sha256
    ):
        """Adopt one proved explicit start; all later checks require exact continuity."""
        if self.plan["schema"] != "deployment-plan-v5":
            return
        # The owner verified the previous process immediately before capture.
        # Accept only a restart inside this successfully completed backup's
        # private evidence window; retain this checkpoint for every later check.
        previous = self._monitoring_expected_state()
        expected = previous["process"]
        proof = self._monitoring_backup_proof(
            phase, intent_sha256, canonical_receipt_sha256
        )
        current = self._inspect()["prometheus"]
        after = process_identity(current)
        began = self._process_started_ns(after)
        require(
            immutable(current) == immutable(self.baseline["containers"]["prometheus"])
            and current["State"]["Running"]
            and not current["State"]["Paused"]
            and not current["State"]["Restarting"]
            and proof["capture_started_ns"] <= began <= proof["capture_finished_ns"]
            and began > self._process_started_ns(expected)
            and after["restart_count"] == 0,
            "host_monitoring_backup_process",
        )
        reload_state = self._monitoring_reload_state(current)
        self._monitoring_backup_reload(reload_state, began, proof)
        directory = self.root / "backup-processes"
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        require(
            stat.S_ISDIR(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o700
            and info.st_uid == os.geteuid(),
            "host_monitoring_backup_directory",
        )
        require(
            phase != "postchange_backup"
            or (directory / "prechange_backup.json").exists(),
            "host_monitoring_backup_order",
        )
        exclusive_record(
            directory / (phase + ".json"),
            {
                "schema": "deployment-backup-process-v1",
                "phase": phase,
                "plan_sha256": digest(encode(self.plan)),
                "profile_sha256": digest(encode(self.profile)),
                "baseline_sha256": self.baseline_sha256,
                "client_intent_sha256": intent_sha256,
                "proof": proof,
                "before": expected,
                "after": after,
                "container_identity_sha256": immutable(current),
                "reload_state": reload_state,
                "previous_reload_timestamp": previous["reload_timestamp"],
            },
        )

    def _monitoring_publish_heartbeat(self):
        current = self._inspect()
        self._preserved(current)
        require(
            current["scheduler"]["State"]["Paused"],
            "host_monitoring_scheduler_not_paused",
        )
        before = self.baseline["monitoring"]["heartbeat_file"]
        name = "docker/scripts/scheduler-heartbeat.sh"
        require(
            self._monitoring_file(name) == before, "host_monitoring_heartbeat_changed"
        )
        raw = (self.candidate / name).read_bytes()
        require(
            digest(raw) == self.plan["monitoring_sha256"][name],
            "host_monitoring_candidate",
        )
        fd = os.open(self.install / name, os.O_WRONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            require(
                (
                    info.st_ino,
                    info.st_dev,
                    stat.S_IMODE(info.st_mode),
                    info.st_uid,
                    info.st_gid,
                    info.st_nlink,
                )
                == (
                    before["inode"],
                    before["device"],
                    before["mode"],
                    before["uid"],
                    before["gid"],
                    1,
                ),
                "host_monitoring_inode_changed",
            )
            offset = 0
            while offset < len(raw):
                count = os.write(fd, raw[offset:])
                require(count > 0, "host_monitoring_write")
                offset += count
            os.ftruncate(fd, len(raw))
            os.fsync(fd)
        finally:
            os.close(fd)
        self._monitoring_mounts(self._inspect())
        blob = self._git(
            self.install,
            "rev-parse",
            self.plan["source"]["candidate_commit"] + ":" + name,
        )
        require(bool(re.fullmatch(r"[0-9a-f]{40}", blob)), "host_monitoring_blob")
        self._git(
            self.install, "update-index", "--cacheinfo", "100755," + blob + "," + name
        )

    def _monitoring_reload(self):
        """Publish one HUP only from the latest proved startup reload state."""
        containers = self._inspect()
        self._monitoring_mounts(containers)
        for name in (
            "docker/scripts/scheduler-heartbeat.sh",
            "docker/prometheus/alert_rules.yml",
        ):
            require(
                self._monitoring_file(name)["sha256"]
                == self.plan["monitoring_sha256"][name],
                "host_monitoring_published_bytes",
            )
        prometheus = containers["prometheus"]
        before = self._monitoring_reload_state(prometheus)
        require(
            before["success"] == 1
            and before["timestamp"]
            == self._monitoring_expected_state()["reload_timestamp"],
            "host_monitoring_reload_drift",
        )
        self._run(
            [
                "docker",
                "exec",
                prometheus["Id"],
                "/bin/promtool",
                "check",
                "config",
                "/etc/prometheus/prometheus.yml",
            ],
            "monitoring-config-check",
        )
        self._run(
            ["docker", "kill", "--signal", "HUP", prometheus["Id"]], "monitoring-reload"
        )
        deadline = time.monotonic() + self.host["readiness_timeout_seconds"]
        while True:
            state = self._monitoring_reload_state(prometheus)
            if state["success"] == 1 and state["timestamp"] > before["timestamp"]:
                self._preserved(self._inspect())
                rules_sha256 = self._monitoring_loaded_rules(prometheus)
                if rules_sha256 is not None:
                    private_bytes(
                        self.root / "monitoring-reload.private.json", encode(state)
                    )
                    private_bytes(
                        self.root / "monitoring-loaded-rules.private.json",
                        encode({"sha256": rules_sha256}),
                    )
                    return
            require(time.monotonic() < deadline, "host_monitoring_reload_failed")
            time.sleep(1)

    def _monitoring_observe_heartbeat(self, resumed_at):
        deadline = time.monotonic() + self.host["readiness_timeout_seconds"]
        while True:
            current = self._inspect()
            self._preserved(current)
            raw = self._container_file(
                current["scheduler"],
                "/var/lib/node_exporter/textfile_collector/scheduler-heartbeat.prom",
                "monitoring-heartbeat-after",
            )
            heartbeat = self._metric(raw, "scheduler_heartbeat_timestamp_seconds")
            hold_names = (
                "scheduler_retention_hold_active",
                "scheduler_retention_hold_invalid",
                "scheduler_retention_hold_cutoff_timestamp_seconds",
                "scheduler_retention_hold_observed_timestamp_seconds",
            )
            # A cron invocation paused before its timestamp assignment can finish
            # once with the old format. Wait for the next ordinary invocation;
            # partially present or contradictory new proof still fails closed.
            has_hold_fields = any(
                re.search(rb"^" + name.encode() + rb"(?:[ {]|$)", raw, re.MULTILINE)
                for name in hold_names
            )
            if (
                heartbeat > self.baseline["monitoring"]["heartbeat_timestamp"]
                and heartbeat >= resumed_at
                and has_hold_fields
            ):
                require(
                    self._metric(raw, "scheduler_retention_hold_active") == 1
                    and self._metric(raw, "scheduler_retention_hold_invalid") == 0
                    and self._metric(
                        raw, "scheduler_retention_hold_cutoff_timestamp_seconds"
                    )
                    > 0
                    and self._metric(
                        raw, "scheduler_retention_hold_observed_timestamp_seconds"
                    )
                    == heartbeat
                    and 0 <= time.time() - heartbeat < 180,
                    "host_monitoring_hold_proof",
                )
                reload_state = self._monitoring_reload_state(current["prometheus"])
                saved_reload = private_json(
                    self.root / "monitoring-reload.private.json"
                )
                require(
                    reload_state == saved_reload and reload_state["success"] == 1,
                    "host_monitoring_reload_drift",
                )
                scraped = self._monitoring_scraped_hold(
                    current["prometheus"], heartbeat
                )
                if scraped is not None:
                    private_bytes(
                        self.root / "monitoring-heartbeat.private.json",
                        encode(
                            {
                                "timestamp": heartbeat,
                                "ordinary_heartbeat_observed": True,
                                "hold_proof_verified": True,
                                **scraped,
                            }
                        ),
                    )
                    return
            require(
                time.monotonic() < deadline, "host_monitoring_heartbeat_not_observed"
            )
            time.sleep(2)

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

    def verify_backup_resumption(
        self, phase, intent_sha256, started, *, canonical_receipt_sha256=None
    ):
        """Verify resumed writers once, joining v5 to the capture payload receipt hash."""
        from .deployment_protocol import effect_guard

        seconds = effect_guard(
            self.plan, self.profile, self.approval, phase, current_time=started
        )
        require(phase.endswith("_backup"), "host_backup_phase")
        require(is_digest(intent_sha256), "host_intent_digest")
        self.effect_until = timestamp(started) + timedelta(seconds=seconds)
        try:
            self._verify_backup_resumption(
                phase,
                intent_sha256,
                started,
                canonical_receipt_sha256=canonical_receipt_sha256,
            )
        finally:
            self.effect_until = None

    def _verify_backup_resumption(
        self, phase, intent_sha256, started, *, canonical_receipt_sha256=None
    ):
        """Persist the process proof before the separately journaled route verification."""
        self._monitoring_accept_backup_process(
            phase, intent_sha256, canonical_receipt_sha256
        )
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
        self._heap_runtime(containers)
        require(self.baseline is not None, "host_baseline_missing")
        self._monitoring_preserved(containers)
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
            configuration = services[service]
            build_only_web = service == "web" and "image" not in configuration
            if build_only_web:
                build = configuration.get("build")
                require(
                    isinstance(build, dict)
                    and isinstance(build.get("context"), str)
                    and bool(build["context"].strip()),
                    "host_consumer_image",
                )
                # Compose does not materialize an image reference for build-only
                # web. Use the existing container's reference, never guess a tag.
                reference = containers[service]["Config"].get("Image")
            else:
                reference = configuration.get("image")
            require(
                isinstance(reference, str) and bool(reference.strip()),
                "host_consumer_image",
            )
            images = {containers[name]["Image"] for name in expected}
            require(
                all(
                    build_only_web or services[name].get("image") == reference
                    for name in expected
                ),
                "host_consumer_image",
            )
            require(
                {
                    name
                    for name, configuration in services.items()
                    if configuration.get("image") == reference
                    or containers[name]["Image"] in images
                    or containers[name]["Config"].get("Image") == reference
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
        baseline_exists = path.exists()
        if baseline_exists:
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
            if "api" in self.plan[
                "services"
            ] and "matrix-alert-relay" in self._consumers("api"):
                # A shared Compose reference may have been recreated at different
                # releases. Each immutable original must exist for exact rollback.
                for image in sorted(
                    {containers[name]["Image"] for name in self._consumers("api")}
                ):
                    require(
                        self._image(image)["Id"] == image,
                        "host_original_image_identity",
                    )
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
            if self.plan["schema"] == "deployment-plan-v5":
                self.baseline["monitoring"] = self._monitoring_baseline(containers)
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
        require(
            self.baseline["compose_sha256"] == digest(encode(config))
            and self.baseline["env_sha256"]
            == digest((self.install / "docker/.env").read_bytes()),
            "host_configuration_changed",
        )
        require(
            self._preserved_data(containers) == self.baseline["protected_data"]
            and self._scheduler_jobs(containers["scheduler"])
            == self.baseline["scheduler_jobs"],
            "host_preservation_baseline_changed",
        )
        if not effects:
            # Establish the actual preserved routes before the first release
            # effect; container health alone cannot prove the proxy destination.
            self._api_ready(containers, effects)
            if "web" in self.plan["services"]:
                self._ready(
                    "web",
                    containers,
                    self.baseline["containers"]["web"]["Image"],
                    self.baseline["old_build_ids"]["web"],
                    reload_nginx=False,
                )
        if not baseline_exists:
            private_bytes(path, encode(self.baseline))
        self.baseline_sha256 = digest(path.read_bytes())
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
        if service == "api":
            self._api_route(expected_build, wait=wait_for_route)
        else:
            self._web_route(expected_build, wait=wait_for_route)

    def _web_route(self, expected_build, *, wait=False):
        until = time.monotonic() + self.host["readiness_timeout_seconds"]
        while True:
            remaining = until - time.monotonic()
            require(remaining > 0, "host_nginx_web_route_unavailable")
            try:
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
                        self.host["nginx_url"].rstrip("/") + "/",
                    ],
                    "route",
                    min(15, max(1, int(remaining))),
                )
                if expected_build.encode() in page:
                    return
                require(wait, "host_nginx_web_build")
            except HostCommandError:
                if not wait:
                    raise
            require(wait, "host_nginx_web_route_unavailable")
            remaining = until - time.monotonic()
            require(remaining > 0, "host_nginx_web_route_unavailable")
            time.sleep(min(0.2, remaining))

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
            # Reload completion does not mean the new workers serve requests yet.
            # Retry only route observations; never repeat the switch or reload.
            self._ready(
                name,
                current,
                image["image_id"],
                image["build_id"],
                wait_for_route=True,
            )
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
        heap = bool(self.plan.get("preserved_heap_sha256"))
        monitoring = self.plan["schema"] == "deployment-plan-v5"
        if heap:
            # The effect journal already owns this once-only publication. Adopt
            # only the reviewed candidate-identical blob, without rewriting the
            # live Compose file or staging any unrelated working-tree content.
            name = "docker/docker-compose.yml"
            blob = self._git(
                self.install, "rev-parse", source["candidate_commit"] + ":" + name
            )
            require(bool(re.fullmatch(r"[0-9a-f]{40}", blob)), "host_heap_blob")
            self._heap_worktree()
            self._git(
                self.install,
                "update-index",
                "--cacheinfo",
                "100644," + blob + "," + name,
            )
        if monitoring:
            self._monitoring_publish_heartbeat()
        self._git(
            self.install, "merge", "--ff-only", "--no-edit", source["candidate_commit"]
        )
        self._source(published=True)
        if heap or monitoring:
            self._configuration()
        if monitoring:
            self._monitoring_reload()
        self._preserved(self._inspect())
        result = {
            "candidate_commit": source["candidate_commit"],
            "candidate_tree": source["candidate_tree"],
            "previous_commit": source["previous_commit"],
            "source_clean": True,
            "unrelated_preserved": True,
        }
        if heap:
            result["preserved_heap_reconciled"] = True
        if monitoring:
            result.update(
                monitoring_files_verified=True, prometheus_reload_verified=True
            )
        return result

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
                    wait_for_route=True,
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
        resumed_at = int(time.time())
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
        result = {
            "scheduler_id": before["Id"],
            "original_process_preserved": True,
            "original_pause_restored": True,
            "job_config_preserved": True,
            "unrelated_preserved": True,
        }
        if self.plan["schema"] == "deployment-plan-v5":
            self._monitoring_observe_heartbeat(resumed_at)
            result["monitoring_heartbeat_observed"] = True
        return result

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

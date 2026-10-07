"""Shared shell pause handling with synthetic Docker and real Linux flock."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_deployment_rehearsal import FIXTURES, SOURCE, container, private_record


class SchedulerPauseShell(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.install = self.root / "install"
        (self.install / "docker").mkdir(parents=True)
        (self.install / "docker/.env").write_text("COMPOSE_PROJECT_NAME=fixture\n")
        control = self.install / "failed_updates/disaster-recovery"
        control.mkdir(parents=True, mode=0o700)
        self.fd = os.open(control / "recovery.lock", os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, self.fd)
        (self.root / "bin").mkdir()
        boundary = self.root / "bin/boundary.py"
        shutil.copyfile(FIXTURES / "boundary.py", boundary)
        boundary.chmod(0o700)
        (self.root / "bin/docker").symlink_to("boundary.py")
        private_record(
            self.root / "boundary-state.json",
            {
                "calls": [],
                "containers": {
                    service: container(service, self.install, "build-01234567")
                    for service in ("api", "web", "scheduler")
                },
            },
        )
        self.env = {
            "PATH": str(self.root / "bin") + os.pathsep + os.environ["PATH"],
            "HOME": str(self.root),
        }

    def state(self):
        return json.loads((self.root / "boundary-state.json").read_text())

    def pause(self, service, action="pause"):
        subprocess.run(
            [
                str(self.root / "bin/docker"),
                action,
                self.state()["containers"][service]["Id"],
            ],
            env=self.env,
            check=True,
            capture_output=True,
        )

    def config(self, *, inherited=True, legacy=False):
        env = self.env.copy()
        if inherited:
            env["BISQ_SUPPORT_LIFECYCLE_LOCK_FD"] = str(self.fd)
        if legacy:
            command = [
                "bash",
                "-c",
                'set -euo pipefail; source "$1"; setup_colors; '
                'pin_existing_compose_project "$2/docker" docker-compose.yml existing',
                "--",
                str(SOURCE / "scripts/lib/common.sh"),
                str(self.install),
            ]
        else:
            command = [
                "bash",
                str(SOURCE / "scripts/lib/deployment_host.sh"),
                "config",
                str(self.install),
                "fixture",
            ]
        return subprocess.run(
            command,
            env=env,
            pass_fds=(self.fd,) if inherited else (),
            capture_output=True,
            text=True,
            timeout=10,
        )

    def backup_inventory(self, *, inherited=True, plan_owner="a" * 64):
        env = self.env | {
            "BISQ_SUPPORT_INSTALL_DIR": str(self.install),
            "BISQ_SUPPORT_DEPLOYMENT_PLAN_SHA256": plan_owner,
        }
        if inherited:
            env["BISQ_SUPPORT_LIFECYCLE_LOCK_FD"] = str(self.fd)
        # Run the actual main/acquire/Compose inventory chain. Isolate unrelated
        # target validation and stop before any snapshot/writer/encryption work.
        command = [
            "bash",
            "-c",
            'source "$1"; '
            "validate_configuration() { :; }; "
            "capture_backup_target_identity() { :; }; "
            "validate_api_data_mount() { printf 'inventory-passed\\n'; return 73; }; "
            "main",
            "--",
            str(SOURCE / "scripts/backup.sh"),
        ]
        return subprocess.run(
            command,
            env=env,
            pass_fds=(self.fd,) if inherited else (),
            capture_output=True,
            text=True,
            timeout=10,
        )

    def active_controller(self):
        private_record(
            self.install / "failed_updates/disaster-recovery/deployment-active.json",
            {
                "schema": "deployment-active-v1",
                "plan_sha256": "a" * 64,
                "profile_sha256": "b" * 64,
                "operation": str(self.root / "operation"),
            },
        )

    def test_boundary_models_actual_docker_pause_status(self):
        self.pause("scheduler")
        state = self.state()["containers"]["scheduler"]["State"]
        self.assertEqual(state["Status"], "paused")
        self.assertTrue(state["Paused"])
        self.assertTrue(state["Running"])
        self.pause("scheduler", "unpause")
        state = self.state()["containers"]["scheduler"]["State"]
        self.assertEqual(state["Status"], "running")
        self.assertFalse(state["Paused"])

    def test_paused_scheduler_without_owner_is_refused(self):
        self.pause("scheduler")
        for inherited in (False, True):
            with self.subTest(inherited_but_unlocked=inherited):
                result = self.config(inherited=inherited)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("not an owned scheduler", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "real Linux /proc/flock proof")
    def test_initially_paused_scheduler_keeps_state_under_real_owner(self):
        self.pause("scheduler")
        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = self.state()["containers"]["scheduler"]
        result = self.config()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.state()["containers"]["scheduler"])

    @unittest.skipUnless(sys.platform == "linux", "real Linux /proc/flock proof")
    def test_newly_paused_scheduler_is_revalidated_under_real_owner(self):
        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = self.config()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.pause("scheduler")
        result = self.config()
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "real Linux /proc/flock proof")
    def test_legacy_and_other_paused_services_refuse_even_under_owner(self):
        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.pause("scheduler")
        result = self.config(legacy=True)
        self.assertNotEqual(result.returncode, 0)
        self.pause("scheduler", "unpause")
        for service in ("api", "web"):
            with self.subTest(service=service):
                self.pause(service)
                result = self.config()
                self.assertNotEqual(result.returncode, 0)
                self.pause(service, "unpause")

    @unittest.skipUnless(sys.platform == "linux", "real Linux /proc/flock proof")
    def test_inconsistent_paused_scheduler_refuses_under_real_owner(self):
        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.pause("scheduler")
        for field in ("Paused", "Running"):
            with self.subTest(field=field):
                state = self.state()
                state["containers"]["scheduler"]["State"][field] = False
                private_record(self.root / "boundary-state.json", state)
                result = self.config()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("scheduler state is invalid", result.stderr)
                state["containers"]["scheduler"]["State"][field] = True
                private_record(self.root / "boundary-state.json", state)

    @unittest.skipUnless(sys.platform == "linux", "real Linux /proc/flock proof")
    def test_backup_main_inventory_accepts_only_bound_borrowed_controller(self):
        self.pause("scheduler")
        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = self.state()["containers"]
        # A plan-shaped environment value alone supplies no controller proof.
        result = self.backup_inventory()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("inventory-passed", result.stdout)
        self.active_controller()
        result = self.backup_inventory(plan_owner="c" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("inventory-passed", result.stdout)
        # Both prechange and postchange backup entry points can inventory the
        # same held scheduler without resuming or replacing its process.
        for _ in range(2):
            result = self.backup_inventory()
            self.assertEqual(result.returncode, 73, result.stdout + result.stderr)
            self.assertIn("inventory-passed", result.stdout)
        self.assertEqual(before, self.state()["containers"])
        # Owning a freshly acquired standalone lock is not the borrowed path.
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        result = self.backup_inventory(inherited=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("inventory-passed", result.stdout)

    @unittest.skipUnless(sys.platform == "linux", "real Linux /proc/flock proof")
    def test_backup_main_refuses_paused_api_or_web_for_controller(self):
        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.active_controller()
        for service in ("api", "web"):
            with self.subTest(service=service):
                self.pause(service)
                result = self.backup_inventory()
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("inventory-passed", result.stdout)
                self.pause(service, "unpause")


if __name__ == "__main__":
    unittest.main()

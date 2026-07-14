"""Runtime tests for Compose-owned public-boundary secrets."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INITIALIZER = PROJECT_ROOT / "docker" / "scripts" / "init-runtime-secret.sh"
LOADER = PROJECT_ROOT / "docker" / "scripts" / "lib" / "runtime-secret.sh"


def _run_initializer(secret_file: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "RUNTIME_SECRET_FILE": str(secret_file),
            "RUNTIME_SECRET_LABEL": "test boundary secret",
        }
    )
    return subprocess.run(
        ["/bin/sh", str(INITIALIZER)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )


def _run_loader(secret_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/bin/sh",
            "-c",
            (
                '. "$1"; '
                'load_runtime_secret_from_file TEST_RUNTIME_SECRET "$2"; '
                'test "$TEST_RUNTIME_SECRET" = "$3"'
            ),
            "runtime-secret-test",
            str(LOADER),
            str(secret_file),
            "a" * 64,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_initializer_generates_once_without_rotating(tmp_path: Path) -> None:
    secret_file = tmp_path / "secret"

    first = _run_initializer(secret_file)

    assert first.returncode == 0, first.stderr
    first_value = secret_file.read_bytes()
    assert re.fullmatch(rb"[0-9a-f]{64}", first_value)
    assert stat.S_IMODE(secret_file.stat().st_mode) == 0o444

    second = _run_initializer(secret_file)

    assert second.returncode == 0, second.stderr
    assert secret_file.read_bytes() == first_value
    assert "Preserving existing test boundary secret" in second.stdout


@pytest.mark.parametrize(
    "invalid_value",
    [
        b"",
        b"a" * 63,
        b"a" * 64 + b"\n",
        b"g" * 64,
    ],
)
def test_initializer_fails_closed_without_replacing_invalid_existing_file(
    tmp_path: Path,
    invalid_value: bytes,
) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_bytes(invalid_value)

    result = _run_initializer(secret_file)

    assert result.returncode != 0
    assert secret_file.read_bytes() == invalid_value
    assert "Failed to initialize test boundary secret" in result.stderr


def test_initializer_rejects_symbolic_link(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("a" * 64, encoding="utf-8")
    secret_file = tmp_path / "secret"
    secret_file.symlink_to(target)

    result = _run_initializer(secret_file)

    assert result.returncode != 0
    assert target.read_text(encoding="utf-8") == "a" * 64
    assert "symbolic links are not allowed" in result.stderr


def test_runtime_loader_exports_only_a_valid_fixed_format_secret(
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_text("a" * 64, encoding="utf-8")

    result = _run_loader(secret_file)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("invalid_value", ["", "a" * 63, "a" * 64 + "\n", "g" * 64])
def test_runtime_loader_fails_closed_on_invalid_secret(
    tmp_path: Path,
    invalid_value: str,
) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_text(invalid_value, encoding="utf-8")

    result = _run_loader(secret_file)

    assert result.returncode != 0
    assert "Required runtime secret" in result.stderr

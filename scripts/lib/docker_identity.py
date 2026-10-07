#!/usr/bin/env python3
"""Hash a complete Docker container identity without treating mount order as state.

Input is the existing backup identity projection, not an entire inspect result::

    {"Id": ..., "Image": ..., "Created": ..., "Config": {...}, "Mounts": [...]}

Only JSON object ordering and the outer Mounts list ordering are immaterial.
Mount multiplicity, every mount/config field and every nested list remain part
of the identity. Process state is deliberately absent: a permitted writer
stop/start changes PID/StartedAt. Callers must verify process continuity
separately for services such as a scheduler that must never restart.

This module invokes no Docker command and performs no filesystem writes. The
CLI accepts the expected full container ID and emits only a SHA-256 or a fixed
error code; Config may contain secrets and must never be echoed on failure.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any

IDENTITY_KEYS = frozenset({"Id", "Image", "Created", "Config", "Mounts"})
MAX_INPUT_BYTES = 16 * 1024 * 1024


class DockerIdentityError(ValueError):
    """Invalid or mismatched input; messages never include inspect values."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DockerIdentityError("docker_identity_invalid")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise DockerIdentityError("docker_identity_invalid")


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def container_identity_sha256(inspect_json: bytes | str, expected_id: str) -> str:
    """Return the stable digest of one exact, full-ID identity projection.

    Reject duplicate JSON keys rather than silently selecting one value. Do not
    deduplicate Mounts: adding an identical mount must change the digest too.
    The encoded identity follows the existing operational format (UTF-8 JSON,
    sorted object keys, compact separators, no trailing newline).
    """
    try:
        if not isinstance(expected_id, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_id
        ):
            raise DockerIdentityError("docker_identity_invalid")
        if isinstance(inspect_json, str):
            inspect_json = inspect_json.encode("utf-8")
        if not isinstance(inspect_json, bytes) or len(inspect_json) > MAX_INPUT_BYTES:
            raise DockerIdentityError("docker_identity_invalid")
        value = json.loads(
            inspect_json,
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
        if not isinstance(value, dict) or set(value) != IDENTITY_KEYS:
            raise DockerIdentityError("docker_identity_invalid")
        if value["Id"] != expected_id:
            raise DockerIdentityError("docker_identity_invalid")
        if any(
            not isinstance(value[key], str) or not value[key]
            for key in ("Image", "Created")
        ):
            raise DockerIdentityError("docker_identity_invalid")
        if (
            not isinstance(value["Config"], dict)
            or not isinstance(value["Mounts"], list)
            or not all(isinstance(mount, dict) for mount in value["Mounts"])
        ):
            raise DockerIdentityError("docker_identity_invalid")
        value["Mounts"] = sorted(value["Mounts"], key=_canonical)
        return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()
    except (ValueError, TypeError, RecursionError) as error:
        raise DockerIdentityError("docker_identity_invalid") from error


def main() -> int:
    try:
        if len(sys.argv) != 2:
            raise DockerIdentityError("docker_identity_invalid")
        digest = container_identity_sha256(
            sys.stdin.buffer.read(MAX_INPUT_BYTES + 1), sys.argv[1]
        )
    except (DockerIdentityError, OSError):
        print("docker_identity_invalid", file=sys.stderr)
        return 2
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

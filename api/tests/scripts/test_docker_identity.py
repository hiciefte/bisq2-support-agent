"""Exercise the canonical helper and its shell-facing entrypoint, without Docker."""

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3] / "scripts/lib/docker_identity.py"
SPEC = importlib.util.spec_from_file_location("docker_identity", SOURCE)
assert SPEC is not None and SPEC.loader is not None
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)
CID = "a" * 64
pytestmark = pytest.mark.unit


@pytest.fixture
def container():
    return {
        "Id": CID,
        "Image": "sha256:" + "b" * 64,
        "Created": "2026-10-01T13:00:00.123456789Z",
        "Config": {
            "Labels": {"com.docker.compose.service": "fixture", "label": "日本語"},
            "Env": ["A=1", "B=2"],
            "Cmd": ["run", "--flag"],
            "Entrypoint": ["sh", "-c"],
            "Healthcheck": {"Test": ["CMD", "check"], "Interval": 5000000},
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": "fixture-data",
                "Source": "/fixture/volume",
                "Destination": "/data",
                "Driver": "local",
                "Mode": "rw",
                "RW": True,
                "Propagation": "",
            },
            {
                "Type": "bind",
                "Source": "/fixture/config",
                "Destination": "/etc/config",
                "Mode": "ro",
                "RW": False,
                "Propagation": "rprivate",
            },
        ],
    }


def digest(value, expected_id=CID):
    return identity.container_identity_sha256(json.dumps(value), expected_id)


def run_cli(payload, *args):
    return subprocess.run(
        [sys.executable, "-I", "-B", str(SOURCE), *args],
        input=payload,
        capture_output=True,
        timeout=10,
    )


def test_object_and_mount_order_have_no_effect(container):
    changed = copy.deepcopy(container)
    changed["Mounts"] = [
        dict(reversed(list(mount.items()))) for mount in reversed(changed["Mounts"])
    ]
    changed["Config"]["Labels"] = dict(
        reversed(list(changed["Config"]["Labels"].items()))
    )
    changed["Config"] = dict(reversed(list(changed["Config"].items())))
    changed = dict(reversed(list(changed.items())))
    assert digest(changed) == digest(container)
    # Actual CLI is the interface a future Bash caller will use, not a copy of
    # the implementation embedded in a test or generated callback.
    result = run_cli(json.dumps(changed).encode(), CID)
    assert result.returncode == 0
    assert result.stdout == (digest(container) + "\n").encode()
    assert result.stderr == b""


def test_encoding_matches_existing_operational_format(container):
    # Deliberately pin a known fixture, so changing normalization invalidates
    # this contract even if both newly produced hashes would still compare equal.
    assert (
        digest(container)
        == "e00b6ac426a3d2d877519d0bd1037492bd66289434b29a4d32dba05f00084de3"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Source", "/different"),
        ("Destination", "/different"),
        ("Name", "new-volume"),
        ("Driver", "different"),
        ("Mode", "ro"),
        ("RW", False),
        ("Propagation", "rshared"),
        ("UnknownDockerField", {"present": True}),
    ],
)
def test_every_mount_field_affects_identity(container, field, value):
    changed = copy.deepcopy(container)
    changed["Mounts"][0][field] = value
    assert digest(changed) != digest(container)


def test_mount_multiplicity_is_preserved(container):
    duplicated = copy.deepcopy(container)
    duplicated["Mounts"].append(copy.deepcopy(container["Mounts"][0]))
    assert digest(duplicated) != digest(container)
    reordered = copy.deepcopy(duplicated)
    reordered["Mounts"].reverse()
    assert digest(reordered) == digest(duplicated)
    removed = copy.deepcopy(container)
    removed["Mounts"].pop()
    assert digest(removed) != digest(container)


@pytest.mark.parametrize("field", ["Env", "Cmd", "Entrypoint"])
def test_config_list_order_is_not_normalized(container, field):
    changed = copy.deepcopy(container)
    changed["Config"][field].reverse()
    assert digest(changed) != digest(container)


def test_nested_lists_and_unknown_config_fields_are_preserved(container):
    changed = copy.deepcopy(container)
    changed["Config"]["Healthcheck"]["Test"].reverse()
    assert digest(changed) != digest(container)
    changed = copy.deepcopy(container)
    changed["Config"]["FutureDockerField"] = {"nested": ["one", "two"]}
    assert digest(changed) != digest(container)
    reordered = copy.deepcopy(changed)
    reordered["Config"]["FutureDockerField"]["nested"].reverse()
    assert digest(reordered) != digest(changed)
    changed = copy.deepcopy(container)
    changed["Mounts"][0]["Options"] = ["one", "two"]
    reordered = copy.deepcopy(changed)
    reordered["Mounts"][0]["Options"].reverse()
    assert digest(reordered) != digest(changed)


@pytest.mark.parametrize("field", ["Image", "Created"])
def test_container_identity_fields_are_significant(container, field):
    changed = copy.deepcopy(container)
    changed[field] += "changed"
    assert digest(changed) != digest(container)


def test_exact_container_id_required(container):
    changed = dict(container, Id="c" * 64)
    with pytest.raises(identity.DockerIdentityError):
        digest(changed)
    assert digest(changed, "c" * 64) != digest(container)
    for expected in (CID[:12], "A" * 64, None, 42):
        with pytest.raises(identity.DockerIdentityError):
            digest(container, expected)


def test_empty_mounts_are_valid(container):
    container["Mounts"] = []
    assert len(digest(container)) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Config", []),
        ("Mounts", {}),
        ("Mounts", ["wrong"]),
        ("Image", ""),
        ("Created", None),
    ],
)
def test_invalid_projection_refuses(container, field, value):
    container[field] = value
    with pytest.raises(identity.DockerIdentityError):
        digest(container)


def test_no_silent_projection_of_extra_fields(container):
    container["State"] = {"Pid": 123}
    with pytest.raises(identity.DockerIdentityError):
        digest(container)
    del container["State"]
    del container["Created"]
    with pytest.raises(identity.DockerIdentityError):
        digest(container)


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json PRIVATE_SENTINEL",
        b'{"Id":"PRIVATE_SENTINEL","Id":"duplicate"}',
        b'{"Config":{"nested":1,"nested":2}}',
        b'{"Config":{"value":NaN}}',
        b'{"Config":{"value":Infinity}}',
        b'{"Config":{"value":-Infinity}}',
        b"\xff",
        b"[" * 2000 + b"]" * 2000,
    ],
)
def test_cli_invalid_input_never_echoes_values(payload):
    result = run_cli(payload, CID)
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == b"docker_identity_invalid\n"


def test_nested_duplicate_and_nonfinite_numbers_refuse(container):
    payload = json.dumps(container).replace('"Interval": 5000000', '"Interval": 1e999')
    with pytest.raises(identity.DockerIdentityError):
        identity.container_identity_sha256(payload, CID)
    payload = json.dumps(container).replace(
        '"Interval": 5000000', '"Interval": 5000000, "Interval": 0'
    )
    with pytest.raises(identity.DockerIdentityError):
        identity.container_identity_sha256(payload, CID)


def test_input_bound_and_cli_argument_contract(container, monkeypatch):
    monkeypatch.setattr(identity, "MAX_INPUT_BYTES", 8)
    with pytest.raises(identity.DockerIdentityError):
        digest(container)
    for arguments in ((), (CID, "extra")):
        result = run_cli(b"{}", *arguments)
        assert result.returncode == 2
        assert result.stdout == b""
        assert result.stderr == b"docker_identity_invalid\n"


def test_raw_serialization_reproduces_old_false_mismatch(container):
    reordered = copy.deepcopy(container)
    reordered["Mounts"].reverse()
    old_before = hashlib.sha256(json.dumps(container).encode()).hexdigest()
    old_after = hashlib.sha256(json.dumps(reordered).encode()).hexdigest()
    assert old_before != old_after
    assert digest(container) == digest(reordered)

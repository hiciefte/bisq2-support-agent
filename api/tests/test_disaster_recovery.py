from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from app.scripts import disaster_recovery as dr

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "backup.sh"
RESTORE_SCRIPT = REPO_ROOT / "scripts" / "restore.sh"


def _create_database(path: Path, values: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE records (value TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO records (value) VALUES (?)", [(value,) for value in values]
        )


def _row_count(path: Path) -> int:
    with sqlite3.connect(path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM records").fetchone()[0])


def _write_tar(path: Path, files: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, mode="w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.mode = 0o600
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


def _write_qdrant_archive(path: Path) -> None:
    snapshot = b"qdrant snapshot fixture"
    manifest = {
        "collections": [
            {
                "collection": "documents",
                "file": "collection-0.snapshot",
                "sha256": hashlib.sha256(snapshot).hexdigest(),
                "size_bytes": len(snapshot),
            }
        ],
        "created_at": "2026-01-01T00:00:00+00:00",
        "format_version": 1,
    }
    _write_tar(
        path,
        {
            "manifest.json": (json.dumps(manifest) + "\n").encode(),
            "collection-0.snapshot": snapshot,
        },
    )


def _prepare_bundle(tmp_path: Path) -> tuple[Path, Path, Path]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _create_database(data_dir / "faqs.db", ["one", "two"])
    _create_database(data_dir / "matrix_session_store" / "store.db", ["device"])
    (data_dir / "faqs.db-wal").write_bytes(b"stale wal must not be restored")
    (data_dir / "faqs.db-shm").write_bytes(b"stale shm must not be restored")
    (data_dir / "conversations.jsonl").write_text(
        "old conversation\n", encoding="utf-8"
    )
    (data_dir / "matrix_session.json").write_text(
        '{"session":"old"}\n', encoding="utf-8"
    )
    (data_dir / "vectorstore").mkdir()
    (data_dir / "vectorstore" / "derived.bin").write_bytes(b"derived")

    snapshot_root = tmp_path / "snapshot"
    dr.snapshot_data(data_dir, snapshot_root)
    _write_qdrant_archive(
        snapshot_root / "components" / "qdrant" / "qdrant-snapshots.tar.gz"
    )
    grafana_database = tmp_path / "grafana.db"
    _create_database(grafana_database, ["dashboard"])
    for component in dr.REQUIRED_VOLUME_COMPONENTS:
        files = {"state.txt": f"{component} state".encode()}
        if component == "grafana":
            files["grafana.db"] = grafana_database.read_bytes()
            files["grafana.db-wal"] = b"stale wal"
        archive_path = snapshot_root / "components" / "volumes" / f"{component}.tar.gz"
        raw_archive = archive_path.with_name(f".{component}.raw.tar.gz")
        _write_tar(
            raw_archive,
            files,
        )
        dr.normalize_volume_archive(raw_archive, archive_path)
        raw_archive.unlink()

    env_file = tmp_path / ".env"
    env_file.write_text(
        "ADMIN_API_KEY=secret-value\n"
        "export MATRIX_SYNC_PASSWORD=another-secret\n"
        "# IGNORED=value\n",
        encoding="utf-8",
    )
    dr.create_bundle_manifest(snapshot_root, env_file)
    return data_dir, snapshot_root, env_file


def test_snapshot_and_verify_restore_all_components_in_scratch(
    tmp_path: Path,
) -> None:
    data_dir, snapshot_root, _env_file = _prepare_bundle(tmp_path)

    with sqlite3.connect(data_dir / "faqs.db") as connection:
        connection.execute("INSERT INTO records (value) VALUES ('later')")

    scratch = tmp_path / "scratch"
    summary = dr.verify_bundle(snapshot_root, scratch, ["all"])

    assert summary == {
        "application_files": 4,
        "artifacts": 11,
        "qdrant_collections": 1,
        "sqlite_databases": 3,
        "volumes": 5,
    }
    assert _row_count(scratch / "application-data" / "faqs.db") == 2
    assert (scratch / "application-data" / "matrix_session.json").read_text(
        encoding="utf-8"
    ) == '{"session":"old"}\n'
    assert (scratch / "volumes" / "prometheus" / "state.txt").is_file()
    assert _row_count(scratch / "volumes" / "grafana" / "grafana.db") == 1
    assert (scratch / "volumes" / "bisq2" / "state.txt").is_file()
    assert (scratch / "volumes" / "alertmanager" / "state.txt").is_file()
    assert (scratch / "qdrant" / "collection-0.snapshot").is_file()


def test_manifest_contains_environment_names_but_never_values(tmp_path: Path) -> None:
    _data_dir, snapshot_root, _env_file = _prepare_bundle(tmp_path)

    serialized = (snapshot_root / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(serialized)

    assert manifest["environment_variable_names"] == [
        "ADMIN_API_KEY",
        "MATRIX_SYNC_PASSWORD",
    ]
    assert "secret-value" not in serialized
    assert "another-secret" not in serialized
    assert "IGNORED" not in manifest["environment_variable_names"]


def test_snapshot_excludes_derived_state_and_uses_sqlite_backup_api(
    tmp_path: Path,
) -> None:
    _data_dir, snapshot_root, _env_file = _prepare_bundle(tmp_path)
    application_manifest = json.loads(
        (snapshot_root / "manifest" / "application.json").read_text(encoding="utf-8")
    )

    by_relative_path = {
        entry["relative_path"]: entry for entry in application_manifest["entries"]
    }
    assert "vectorstore/derived.bin" not in by_relative_path
    assert by_relative_path["faqs.db"]["type"] == "sqlite"
    assert by_relative_path["faqs.db"]["sqlite"] == {
        "integrity_check": "ok",
        "row_counts": {"records": 2},
    }
    assert by_relative_path["matrix_session_store/store.db"]["components"] == [
        "sqlite",
        "matrix",
    ]
    assert "faqs.db-wal" not in by_relative_path
    assert "faqs.db-shm" not in by_relative_path


def test_normalize_volume_uses_sqlite_backup_and_omits_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "grafana.db"
    _create_database(database, ["dashboard"])
    source = tmp_path / "raw.tar.gz"
    output = tmp_path / "normalized.tar.gz"
    files = {
        "grafana.db": database.read_bytes(),
        "grafana.db-wal": b"stale wal",
        "state.txt": b"state",
    }
    with tarfile.open(source, mode="w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.uid = 123
            info.gid = 456
            info.mode = 0o640
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    original_backup = dr._sqlite_backup
    backed_up: list[str] = []

    def recording_backup(
        source_path: Path, destination_path: Path
    ) -> dict[str, object]:
        backed_up.append(source_path.name)
        return original_backup(source_path, destination_path)

    monkeypatch.setattr(dr, "_sqlite_backup", recording_backup)

    assert dr.normalize_volume_archive(source, output) == 1

    assert backed_up == ["grafana.db"]
    with tarfile.open(output, mode="r:gz") as archive:
        members = {member.name: member for member in archive}
    with tarfile.open(output, mode="r:gz") as archive:
        dr._safe_extract_archive(archive, tmp_path / "restored")
    assert "grafana.db-wal" not in members
    assert members["grafana.db"].uid == 123
    assert members["grafana.db"].gid == 456
    assert members["grafana.db"].mode == 0o640
    assert _row_count(tmp_path / "restored" / "grafana.db") == 1


def test_verify_rejects_a_tampered_artifact(tmp_path: Path) -> None:
    _data_dir, snapshot_root, _env_file = _prepare_bundle(tmp_path)
    qdrant_archive = snapshot_root / "components" / "qdrant" / "qdrant-snapshots.tar.gz"
    qdrant_archive.write_bytes(qdrant_archive.read_bytes() + b"tampered")

    with pytest.raises(dr.RecoveryError, match="size mismatch"):
        dr.verify_bundle(snapshot_root, tmp_path / "scratch", ["all"])


def test_restore_data_honors_matrix_component_selection(tmp_path: Path) -> None:
    data_dir, snapshot_root, _env_file = _prepare_bundle(tmp_path)
    (data_dir / "conversations.jsonl").write_text(
        "new conversation\n", encoding="utf-8"
    )
    (data_dir / "matrix_session.json").write_text(
        '{"session":"new"}\n', encoding="utf-8"
    )
    with sqlite3.connect(data_dir / "faqs.db") as connection:
        connection.execute("INSERT INTO records (value) VALUES ('new faq')")
    with sqlite3.connect(data_dir / "matrix_session_store" / "store.db") as connection:
        connection.execute("INSERT INTO records (value) VALUES ('new device')")

    restored = dr.restore_data(
        snapshot_root,
        data_dir,
        tmp_path / "rollback",
        ["matrix"],
    )

    assert restored == 2
    assert (data_dir / "matrix_session.json").read_text(
        encoding="utf-8"
    ) == '{"session":"old"}\n'
    assert _row_count(data_dir / "matrix_session_store" / "store.db") == 1
    assert _row_count(data_dir / "faqs.db") == 3
    assert (data_dir / "conversations.jsonl").read_text(
        encoding="utf-8"
    ) == "new conversation\n"


def test_application_restore_can_roll_back_after_a_later_component_failure(
    tmp_path: Path,
) -> None:
    data_dir, snapshot_root, _env_file = _prepare_bundle(tmp_path)
    (data_dir / "matrix_session.json").write_text(
        '{"session":"live"}\n', encoding="utf-8"
    )
    with sqlite3.connect(data_dir / "matrix_session_store" / "store.db") as connection:
        connection.execute("INSERT INTO records (value) VALUES ('live device')")
    rollback_dir = tmp_path / "rollback"

    assert dr.restore_data(snapshot_root, data_dir, rollback_dir, ["matrix"]) == 2
    assert _row_count(data_dir / "matrix_session_store" / "store.db") == 1

    assert dr.rollback_data(data_dir, rollback_dir) == 2

    assert (data_dir / "matrix_session.json").read_text(
        encoding="utf-8"
    ) == '{"session":"live"}\n'
    assert _row_count(data_dir / "matrix_session_store" / "store.db") == 2
    assert not (rollback_dir / "rollback-manifest.json").exists()


def test_selected_restore_removes_absent_files_and_rolls_them_back(
    tmp_path: Path,
) -> None:
    data_dir, snapshot_root, _env_file = _prepare_bundle(tmp_path)
    conversations = data_dir / "conversations.jsonl"
    conversations.write_text("live conversation\n", encoding="utf-8")
    absent_from_backup = data_dir / "late-authoritative.jsonl"
    absent_from_backup.write_text("created later\n", encoding="utf-8")
    unselected_database = data_dir / "created-later.db"
    _create_database(unselected_database, ["keep"])
    derived = data_dir / "vectorstore" / "derived.bin"
    rollback_dir = tmp_path / "rollback"

    assert (
        dr.restore_data(
            snapshot_root,
            data_dir,
            rollback_dir,
            ["application"],
        )
        == 1
    )

    assert conversations.read_text(encoding="utf-8") == "old conversation\n"
    assert not absent_from_backup.exists()
    assert _row_count(unselected_database) == 1
    assert derived.read_bytes() == b"derived"

    assert dr.rollback_data(data_dir, rollback_dir) == 2
    assert conversations.read_text(encoding="utf-8") == "live conversation\n"
    assert absent_from_backup.read_text(encoding="utf-8") == "created later\n"
    assert _row_count(unselected_database) == 1
    assert derived.read_bytes() == b"derived"


def test_sqlite_restore_removes_absent_database_and_rolls_it_back(
    tmp_path: Path,
) -> None:
    data_dir, snapshot_root, _env_file = _prepare_bundle(tmp_path)
    absent_database = data_dir / "created-later.db"
    _create_database(absent_database, ["keep"])
    rollback_dir = tmp_path / "rollback"

    assert (
        dr.restore_data(
            snapshot_root,
            data_dir,
            rollback_dir,
            ["sqlite"],
        )
        == 2
    )
    assert not absent_database.exists()

    assert dr.rollback_data(data_dir, rollback_dir) == 3
    assert _row_count(absent_database) == 1


def test_custom_matrix_session_and_store_are_tagged_from_env(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sync.json").write_text("{}\n", encoding="utf-8")
    _create_database(data_dir / "sync_store" / "crypto.db", ["device"])
    env_file = tmp_path / ".env"
    env_file.write_text("MATRIX_SYNC_SESSION_FILE=/data/sync.json\n", encoding="utf-8")
    snapshot_root = tmp_path / "snapshot"

    manifest = dr.snapshot_data(
        data_dir,
        snapshot_root,
        matrix_state_paths=dr.matrix_state_paths_from_env(env_file),
    )
    by_path = {entry["relative_path"]: entry for entry in manifest["entries"]}

    assert by_path["sync.json"]["components"] == ["matrix"]
    assert by_path["sync_store/crypto.db"]["components"] == ["sqlite", "matrix"]

    (data_dir / "sync.json").write_text('{"session":"live"}\n', encoding="utf-8")
    (data_dir / "sync_store" / "new-state.bin").write_bytes(b"live state")
    assert (
        dr.restore_data(
            snapshot_root,
            data_dir,
            tmp_path / "rollback",
            ["application"],
        )
        == 0
    )
    assert (data_dir / "sync.json").read_text(encoding="utf-8") == (
        '{"session":"live"}\n'
    )
    assert (data_dir / "sync_store" / "new-state.bin").read_bytes() == b"live state"


def test_restore_data_rejects_symlinked_destination_parent(tmp_path: Path) -> None:
    data_dir, snapshot_root, _env_file = _prepare_bundle(tmp_path)
    matrix_store = data_dir / "matrix_session_store"
    shutil.rmtree(matrix_store)
    outside = tmp_path / "outside"
    outside.mkdir()
    matrix_store.symlink_to(outside, target_is_directory=True)
    (data_dir / "matrix_session.json").write_text(
        '{"session":"new"}\n', encoding="utf-8"
    )

    with pytest.raises(dr.RecoveryError, match="symlink"):
        dr.restore_data(
            snapshot_root,
            data_dir,
            tmp_path / "rollback",
            ["matrix"],
        )

    assert not (outside / "store.db").exists()
    assert (data_dir / "matrix_session.json").read_text(
        encoding="utf-8"
    ) == '{"session":"new"}\n'


def test_backup_file_stream_copies_authoritative_file_over_50_mb(
    tmp_path: Path,
) -> None:
    source = tmp_path / "conversations.jsonl"
    destination = tmp_path / "backup" / source.name
    source.write_bytes(b"")
    with source.open("r+b") as stream:
        stream.truncate(51 * 1024 * 1024)

    dr.backup_file(source, destination)

    assert destination.stat().st_size == source.stat().st_size


def test_safe_extract_rejects_parent_traversal(tmp_path: Path) -> None:
    malicious = tmp_path / "malicious.tar.gz"
    _write_tar(malicious, {"../outside.txt": b"not allowed"})

    with tarfile.open(malicious, mode="r:gz") as archive:
        with pytest.raises(dr.RecoveryError, match="Unsafe relative path"):
            dr._safe_extract_archive(archive, tmp_path / "scratch")

    assert not (tmp_path / "outside.txt").exists()


def test_safe_extract_accepts_standard_tar_root_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "standard.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        root = tarfile.TarInfo("./")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        content = b"state"
        info = tarfile.TarInfo("./state.txt")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))

    with tarfile.open(archive_path, mode="r:gz") as archive:
        dr._safe_extract_archive(archive, tmp_path / "scratch")

    assert (tmp_path / "scratch" / "state.txt").read_bytes() == b"state"


def test_extract_stream_cli_accepts_backup_tar_layout(tmp_path: Path) -> None:
    _data_dir, snapshot_root, _env_file = _prepare_bundle(tmp_path)
    archive = subprocess.run(
        ["tar", "-C", str(snapshot_root), "-czf", "-", "."],
        capture_output=True,
        check=True,
    ).stdout
    destination = tmp_path / "extracted"

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "api" / "app" / "scripts" / "disaster_recovery.py"),
            "extract-stream",
            "--destination",
            str(destination),
        ],
        input=archive,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode()
    assert (destination / "manifest.json").is_file()


def test_qdrant_export_and_import_use_native_snapshot_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[tuple[str, str]] = []
    uploads: list[tuple[str, bytes]] = []

    monkeypatch.setattr(dr, "_qdrant_collections", lambda **_kwargs: ["documents"])

    def fake_json(method: str, path: str) -> dict[str, object]:
        requests.append((method, path))
        if method == "POST":
            return {"result": {"name": "server-snapshot"}}
        return {"result": True}

    def fake_download(collection: str, snapshot_name: str, destination: Path) -> None:
        assert collection == "documents"
        assert snapshot_name == "server-snapshot"
        destination.write_bytes(b"native qdrant snapshot")

    monkeypatch.setattr(dr, "_qdrant_json", fake_json)
    monkeypatch.setattr(dr, "_download_qdrant_snapshot", fake_download)
    output = io.BytesIO()
    dr.export_qdrant(output)

    assert requests[0][0] == "POST"
    assert requests[-1][0] == "DELETE"

    def fake_upload(collection: str, snapshot: Path) -> None:
        uploads.append((collection, snapshot.read_bytes()))

    monkeypatch.setattr(dr, "_upload_qdrant_snapshot", fake_upload)
    restored = dr.import_qdrant(io.BytesIO(output.getvalue()), None)

    assert restored == ["documents"]
    assert uploads == [("documents", b"native qdrant snapshot")]


def test_qdrant_rollback_removes_collections_absent_from_preimage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_path = tmp_path / "preimage.tar.gz"
    _write_qdrant_archive(archive_path)
    collections = {"documents", "partially-restored"}
    requests: list[tuple[str, str]] = []

    monkeypatch.setattr(dr, "_upload_qdrant_snapshot", lambda *_args: None)
    monkeypatch.setattr(
        dr,
        "_qdrant_collections",
        lambda **_kwargs: sorted(collections),
    )

    def fake_json(method: str, path: str, timeout: float = 120) -> dict[str, object]:
        requests.append((method, path))
        if method == "DELETE":
            collections.remove(path.rsplit("/", 1)[-1])
        return {"result": True}

    monkeypatch.setattr(dr, "_qdrant_json", fake_json)
    with archive_path.open("rb") as archive:
        restored = dr.import_qdrant(archive, None, delete_absent=True)

    assert restored == ["documents"]
    assert collections == {"documents"}
    assert requests == [("DELETE", "/collections/partially-restored")]


def test_recovery_shell_scripts_have_safe_entrypoints_and_required_flows() -> None:
    result = subprocess.run(
        ["bash", "-n", str(BACKUP_SCRIPT), str(RESTORE_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    backup_content = BACKUP_SCRIPT.read_text(encoding="utf-8")
    restore_content = RESTORE_SCRIPT.read_text(encoding="utf-8")
    assert "--confirm-off-host" in backup_content
    assert "--mount-root" in backup_content
    assert "qdrant-export" in backup_content
    assert "snapshot-data" in backup_content
    assert "normalize-volume" in backup_content
    assert "BACKUP_AGE_RECIPIENT" in backup_content
    assert "BACKUP_GPG_RECIPIENT" in backup_content
    assert 'source "$DOCKER_DIR/.env"' not in backup_content
    assert "snapshot_volume bisq2" in backup_content
    assert "snapshot_volume alertmanager" in backup_content
    assert backup_content.count("validate_api_data_mount") == 2
    assert "verify-bundle" in restore_content
    assert "qdrant-import" in restore_content
    assert "verify_qdrant_in_scratch" in restore_content
    assert "rollback_applied_components" in restore_content
    assert "restore_volume_archive bisq2" in restore_content
    assert "restore_volume_archive alertmanager" in restore_content
    assert restore_content.count("validate_api_data_mount") == 2
    assert "--cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER" in restore_content
    assert "--apply --yes" in restore_content


def test_backup_validation_requires_existing_mounted_target(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    data_dir = install_dir / "api" / "data"
    docker_dir = install_dir / "docker"
    helper = install_dir / "api" / "app" / "scripts" / "disaster_recovery.py"
    data_dir.mkdir(parents=True)
    docker_dir.mkdir(parents=True)
    helper.parent.mkdir(parents=True)
    helper.write_text("# fixture\n", encoding="utf-8")
    (docker_dir / ".env").write_text("NAME=value\n", encoding="utf-8")
    mount_root = tmp_path / "off-host-mount"
    mount_root.mkdir()
    target = mount_root / "backup-sets"

    def validate(mount_status: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "bash",
                "-c",
                f"""
                source "{BACKUP_SCRIPT}"
                TARGET_DIR="{target}"
                MOUNT_ROOT="{mount_root}"
                OFF_HOST_CONFIRMED=true
                RETENTION_DAYS=30
                ENCRYPTION=age
                RECIPIENT=test-recipient
                INSTALL_DIR="{install_dir}"
                DATA_DIR="{data_dir}"
                DOCKER_DIR="{docker_dir}"
                DR_HELPER="{helper}"
                check_required_commands() {{ return 0; }}
                check_docker_daemon() {{ return 0; }}
                check_docker_compose() {{ return 0; }}
                mountpoint() {{ return {mount_status}; }}
                validate_configuration
                """,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    missing = validate(0)
    assert missing.returncode != 0
    assert "Backup target is missing" in missing.stdout + missing.stderr
    assert not target.exists()

    target.mkdir()
    unmounted = validate(1)
    assert unmounted.returncode != 0
    assert "mount root is not mounted" in unmounted.stdout + unmounted.stderr

    mounted = validate(0)
    assert mounted.returncode == 0, mounted.stderr


@pytest.mark.parametrize(
    "script",
    [BACKUP_SCRIPT, RESTORE_SCRIPT],
    ids=["backup", "restore"],
)
@pytest.mark.parametrize(
    ("container_data_dir", "mount_type", "source_kind", "expected_error"),
    [
        ("/unexpected", "bind", "expected", "DATA_DIR must be /data"),
        ("/data", "volume", "expected", "/data must be a bind mount"),
        ("/data", "", "missing", "/data must be a bind mount"),
        ("/data", "bind", "other", "does not match"),
        ("/data", "bind", "expected", None),
    ],
    ids=["wrong-env", "named-volume", "missing-mount", "wrong-source", "valid"],
)
def test_api_data_mount_preflight_fails_closed(
    tmp_path: Path,
    script: Path,
    container_data_dir: str,
    mount_type: str,
    source_kind: str,
    expected_error: str | None,
) -> None:
    install_dir = tmp_path / "install"
    expected_source = install_dir / "api" / "data"
    expected_source.mkdir(parents=True)
    other_source = tmp_path / "other-data"
    other_source.mkdir()
    mount_source = {
        "expected": expected_source,
        "other": other_source,
        "missing": tmp_path / "missing-data",
    }[source_kind]

    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
            source "{script}"
            INSTALL_DIR="{install_dir}"
            FAKE_DATA_DIR="{container_data_dir}"
            FAKE_MOUNT_TYPE="{mount_type}"
            FAKE_MOUNT_SOURCE="{mount_source}"
            container_id_for_service() {{ printf '%s\n' api-container; }}
            docker() {{
                case "$3" in
                    *'.Config.Env'*) printf 'DATA_DIR=%s\n' "$FAKE_DATA_DIR" ;;
                    *'.Type'*) printf '%s\n' "$FAKE_MOUNT_TYPE" ;;
                    *'.Source'*) printf '%s\n' "$FAKE_MOUNT_SOURCE" ;;
                    *) return 1 ;;
                esac
            }}
            validate_api_data_mount
            """,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    if expected_error is None:
        assert result.returncode == 0, output
    else:
        assert result.returncode != 0
        assert expected_error in output


def test_verify_only_restore_does_not_require_live_api_mount(tmp_path: Path) -> None:
    marker = tmp_path / "mount-preflight-called"
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
            source "{RESTORE_SCRIPT}"
            initialize_paths() {{ :; }}
            validate_configuration() {{ :; }}
            validate_api_data_mount() {{ touch "{marker}"; return 1; }}
            decrypt_backup() {{ :; }}
            verify_snapshot() {{ :; }}
            verify_qdrant_in_scratch() {{ :; }}
            main --backup fixture.age --verify --component application
            """,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not marker.exists()


def test_backup_encryption_publishes_atomically_and_tracks_output(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    age = fake_bin / "age"
    age.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        "output=''\n"
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = \'--output\' ]; then output="$2"; shift 2; else shift; fi\n'
        "done\n"
        'test -n "$output"\n'
        'cat > "$output"\n',
        encoding="utf-8",
    )
    age.chmod(0o755)
    staging = tmp_path / "staging"
    target = tmp_path / "target"
    staging.mkdir()
    target.mkdir()
    (staging / "manifest.json").write_text("{}\n", encoding="utf-8")

    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
            set -e
            export PATH="{fake_bin}:$PATH"
            source "{BACKUP_SCRIPT}"
            STAGING_DIR="{staging}"
            TARGET_DIR="{target}"
            ENCRYPTION=age
            RECIPIENT=test-recipient
            encrypt_backup 20260101T000000Z
            printf '%s|%s' "$COMPLETED_OUTPUT_NAME" "$PARTIAL_OUTPUT"
            """,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "bisq-support-backup-20260101T000000Z.tar.gz.age|"
    assert (target / "bisq-support-backup-20260101T000000Z.tar.gz.age").is_file()
    assert not list(target.glob("*.partial.*"))


def test_backup_quiesce_always_records_services_for_restart(tmp_path: Path) -> None:
    command_log = tmp_path / "compose.log"
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
            set -e
            source "{BACKUP_SCRIPT}"
            service_is_running() {{ return 0; }}
            compose() {{ printf '%s\n' "$*" >> "{command_log}"; }}
            quiesce_services
            resume_services
            printf '%s' "${{#QUIESCED_SERVICES[@]}}"
            """,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("0")
    commands = command_log.read_text(encoding="utf-8")
    assert "stop --timeout 30 api" in commands
    assert "stop --timeout 30 grafana" in commands
    assert "stop --timeout 30 bisq2-api" in commands
    assert "stop --timeout 30 alertmanager" in commands
    assert (
        "start scheduler api alertmanager matrix-alert-relay grafana prometheus "
        "bisq2-api"
    ) in commands


def test_qdrant_restore_stops_application_writers(tmp_path: Path) -> None:
    command_log = tmp_path / "compose.log"
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
            set -e
            source "{RESTORE_SCRIPT}"
            COMPONENTS=(qdrant)
            service_is_running() {{ return 0; }}
            compose() {{ printf '%s\n' "$*" >> "{command_log}"; }}
            stop_selected_services
            start_stopped_services
            """,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    commands = command_log.read_text(encoding="utf-8")
    assert "stop --timeout 30 api" in commands
    assert "stop --timeout 30 scheduler" in commands
    assert "start api scheduler" in commands


def test_qdrant_full_restore_deletes_absent_but_selected_restore_does_not(
    tmp_path: Path,
) -> None:
    snapshot_root = tmp_path / "snapshot"
    archive = snapshot_root / "components" / "qdrant" / "qdrant-snapshots.tar.gz"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"fixture")

    def run_restore(component: str, collection: str) -> str:
        command_log = tmp_path / f"{component}.log"
        work_dir = tmp_path / f"{component}-work"
        work_dir.mkdir()
        result = subprocess.run(
            [
                "bash",
                "-c",
                f"""
                set -e
                source "{RESTORE_SCRIPT}"
                COMPONENTS=({component})
                QDRANT_COLLECTION="{collection}"
                WORK_DIR="{work_dir}"
                compose() {{ printf '%s\n' "$*" >> "{command_log}"; }}
                tar() {{ return 0; }}
                restore_qdrant "{snapshot_root}"
                """,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return command_log.read_text(encoding="utf-8")

    full_commands = run_restore("all", "")
    selected_commands = run_restore("qdrant", "documents")

    assert "qdrant-import --delete-absent" in full_commands
    assert "qdrant-import --collection documents" in selected_commands
    assert "--delete-absent" not in selected_commands


def test_qdrant_verification_uses_isolated_scratch_service(tmp_path: Path) -> None:
    command_log = tmp_path / "docker.log"
    snapshot_root = tmp_path / "snapshot"
    archive = snapshot_root / "components" / "qdrant" / "qdrant-snapshots.tar.gz"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"fixture")
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
            set -e
            source "{RESTORE_SCRIPT}"
            COMPONENTS=(qdrant)
            DR_HELPER="{REPO_ROOT / 'api' / 'app' / 'scripts' / 'disaster_recovery.py'}"
            container_id_for_service() {{ printf '%s-id\n' "$1"; }}
            docker() {{
                printf '%s\n' "$*" >> "{command_log}"
                if [ "$1" = inspect ]; then printf '%s-image\n' "$4"; fi
            }}
            verify_qdrant_in_scratch "{snapshot_root}"
            """,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    commands = command_log.read_text(encoding="utf-8")
    assert "network create --internal" in commands
    assert "volume create" in commands
    assert "qdrant-wait --timeout 60" in commands
    assert "qdrant-import" in commands


def test_restore_help_is_safe_without_docker() -> None:
    result = subprocess.run(
        ["bash", str(RESTORE_SCRIPT), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--verify" in result.stdout
    assert "--apply --yes" in result.stdout

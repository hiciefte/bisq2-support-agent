#!/usr/bin/env python3
"""Build, verify, and restore disaster-recovery backup components.

The host-facing shell scripts deliberately keep secret handling and Docker
orchestration outside this module.  This module provides the data operations
that need stronger guarantees than shell copies: SQLite online backups,
manifest verification, safe archive extraction, and Qdrant snapshot API
access.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import http.client
import io
import json
import os
import re
import shlex
import shutil
import sqlite3
import stat
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterable

SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
SQLITE_HEADER = b"SQLite format 3\x00"
SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
EXCLUDED_DATA_PARTS = {
    "__pycache__",
    "evaluation",
    "evaluation_results",
    "logs",
    "vectorstore",
}
REQUIRED_VOLUME_COMPONENTS = (
    "matrix",
    "prometheus",
    "grafana",
    "bisq2",
    "alertmanager",
)
FORMAT_VERSION = 1


class RecoveryError(RuntimeError):
    """Raised when a backup cannot be proven complete or safe."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _safe_relative(raw_path: str) -> Path:
    normalized = raw_path.removeprefix("./")
    path = Path(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise RecoveryError(f"Unsafe relative path in backup: {raw_path!r}")
    return path


def _safe_archive_member(member: tarfile.TarInfo) -> Path:
    if member.issym() or member.islnk() or member.isdev():
        raise RecoveryError(f"Unsupported archive member type: {member.name!r}")
    if not member.isdir() and not member.isfile():
        raise RecoveryError(f"Unsupported archive member: {member.name!r}")
    normalized = member.name
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized in {"", "."}:
        if member.isdir():
            return Path(".")
        raise RecoveryError(f"Unsafe archive member path: {member.name!r}")
    return _safe_relative(normalized)


def _safe_extract_archive(archive: tarfile.TarFile, destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    seen: set[Path] = set()
    for member in archive:
        relative = _safe_archive_member(member)
        if relative == Path("."):
            continue
        if relative in seen:
            raise RecoveryError(f"Duplicate archive member: {relative.as_posix()}")
        seen.add(relative)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            extracted.append(relative)
            continue

        source = archive.extractfile(member)
        if source is None:
            raise RecoveryError(f"Could not read archive member: {member.name!r}")
        with source, target.open("wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
        extracted.append(relative)
    return extracted


def _sqlite_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _is_sqlite_candidate(path: Path) -> bool:
    if path.suffix.lower() in SQLITE_SUFFIXES:
        return True
    with path.open("rb") as source:
        return source.read(len(SQLITE_HEADER)) == SQLITE_HEADER


def _sqlite_sidecar_primary(path: Path) -> Path | None:
    raw_path = str(path)
    for suffix in SQLITE_SIDECAR_SUFFIXES:
        if not raw_path.endswith(suffix):
            continue
        primary = Path(raw_path[: -len(suffix)])
        if (
            primary.is_file()
            and not primary.is_symlink()
            and _is_sqlite_candidate(primary)
        ):
            return primary
    return None


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _sqlite_summary(path: Path) -> dict[str, Any]:
    try:
        with sqlite3.connect(_sqlite_uri(path), uri=True) as connection:
            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            integrity = [str(row[0]) for row in integrity_rows]
            if integrity != ["ok"]:
                raise RecoveryError(
                    f"SQLite integrity_check failed for {path.name}: {integrity}"
                )

            tables = [
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY name"
                )
            ]
            row_counts = {
                table: int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
                    ).fetchone()[0]
                )
                for table in tables
            }
    except sqlite3.Error as exc:
        raise RecoveryError(f"Could not inspect SQLite database {path.name}") from exc

    return {"integrity_check": "ok", "row_counts": row_counts}


def _sqlite_backup(source: Path, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    try:
        with sqlite3.connect(_sqlite_uri(source), uri=True) as source_connection:
            with sqlite3.connect(destination) as destination_connection:
                source_connection.backup(destination_connection, pages=256, sleep=0.05)
    except sqlite3.Error as exc:
        destination.unlink(missing_ok=True)
        raise RecoveryError(f"SQLite backup failed for {source.name}") from exc

    for suffix in ("-wal", "-shm"):
        Path(f"{destination}{suffix}").unlink(missing_ok=True)
    return _sqlite_summary(destination)


def _is_excluded_data_path(relative: Path) -> bool:
    for part in relative.parts:
        if part in EXCLUDED_DATA_PARTS or part.startswith(".backup_"):
            return True
    return relative.name in {".backup.lock", ".disaster-recovery.lock", ".gitignore"}


def _is_matrix_state(relative: Path, explicit_paths: set[Path] | None = None) -> bool:
    if explicit_paths and any(
        relative == configured or configured in relative.parents
        for configured in explicit_paths
    ):
        return True
    lowered_parts = [part.lower() for part in relative.parts]
    if "matrix_session_store" in lowered_parts:
        return True
    lowered_name = relative.name.lower()
    return "matrix" in lowered_name and any(
        marker in lowered_name for marker in ("session", "store", "sync")
    )


def _iter_data_files(data_dir: Path) -> Iterable[tuple[Path, Path]]:
    for path in sorted(data_dir.rglob("*")):
        relative = path.relative_to(data_dir)
        if _is_excluded_data_path(relative):
            continue
        if path.is_symlink():
            raise RecoveryError(f"Refusing to back up symlink: {relative.as_posix()}")
        if path.is_file():
            if _sqlite_sidecar_primary(path) is not None:
                continue
            yield path, relative


def snapshot_data(
    data_dir: Path,
    output_dir: Path,
    matrix_state_paths: set[Path] | None = None,
) -> dict[str, Any]:
    data_dir = data_dir.resolve()
    output_dir = output_dir.resolve()
    if not data_dir.is_dir():
        raise RecoveryError("Application data directory does not exist")
    if output_dir == data_dir or data_dir in output_dir.parents:
        raise RecoveryError("Backup staging directory must be outside application data")

    entries: list[dict[str, Any]] = []
    for source, relative in _iter_data_files(data_dir):
        source_stat = source.stat()
        matrix_state = _is_matrix_state(relative, matrix_state_paths)
        sqlite_file = _is_sqlite_candidate(source)
        if sqlite_file:
            storage_relative = Path("components/sqlite") / relative
            components = ["sqlite"]
            if matrix_state:
                components.append("matrix")
            destination = output_dir / storage_relative
            sqlite_metadata = _sqlite_backup(source, destination)
        else:
            component = "matrix" if matrix_state else "application"
            storage_relative = Path(f"components/{component}") / relative
            components = [component]
            destination = output_dir / storage_relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            sqlite_metadata = None

        entry: dict[str, Any] = {
            "components": components,
            "gid": source_stat.st_gid,
            "mode": stat.S_IMODE(source_stat.st_mode) & 0o777,
            "relative_path": relative.as_posix(),
            "sha256": _sha256(destination),
            "size_bytes": destination.stat().st_size,
            "storage_path": storage_relative.as_posix(),
            "type": "sqlite" if sqlite_file else "file",
            "uid": source_stat.st_uid,
        }
        if sqlite_metadata is not None:
            entry["sqlite"] = sqlite_metadata
        entries.append(entry)

    if not any(entry["type"] == "sqlite" for entry in entries):
        raise RecoveryError("No SQLite databases were found in application data")

    manifest = {
        "created_at": _now_iso(),
        "entries": entries,
        "format_version": FORMAT_VERSION,
    }
    _write_json(output_dir / "manifest/application.json", manifest)
    return manifest


def _environment_assignments(env_file: Path) -> Iterable[tuple[str, str]]:
    if not env_file.is_file() or env_file.is_symlink():
        raise RecoveryError("Docker environment file is unavailable or unsafe")

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not ENV_NAME_RE.fullmatch(name):
            raise RecoveryError("Invalid variable name in Docker environment file")
        yield name, value.strip()


def _environment_variable_names(env_file: Path) -> list[str]:
    return sorted({name for name, _value in _environment_assignments(env_file)})


def _unquote_env_value(raw_value: str) -> str:
    try:
        values = shlex.split(raw_value, comments=True, posix=True)
    except ValueError as exc:
        raise RecoveryError("Invalid quoted Matrix session path") from exc
    if not values:
        return ""
    if len(values) != 1:
        raise RecoveryError("Matrix session path with spaces must be quoted")
    return values[0]


def matrix_state_paths_from_values(configured_values: Iterable[str]) -> set[Path]:
    paths = {Path("matrix_session.json"), Path("matrix_alert_session.json")}
    for value in configured_values:
        if not value:
            continue
        configured = Path(value)
        if configured.is_absolute():
            try:
                configured = configured.relative_to("/data")
            except ValueError as exc:
                raise RecoveryError(
                    "Configured Matrix session path is outside persistent DATA_DIR"
                ) from exc
        configured = _safe_relative(configured.as_posix())
        if configured == Path("."):
            raise RecoveryError("Configured Matrix session path must name a file")
        paths.add(configured)
        paths.add(configured.parent / f"{configured.stem}_store")
    return paths


def matrix_state_paths_from_env(env_file: Path) -> set[Path]:
    configured_values = [
        _unquote_env_value(value)
        for name, value in _environment_assignments(env_file)
        if name in {"MATRIX_SYNC_SESSION_FILE", "MATRIX_ALERT_SESSION_FILE"}
    ]
    return matrix_state_paths_from_values(configured_values)


def _read_qdrant_manifest(archive_path: Path) -> dict[str, Any]:
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = {
            _safe_archive_member(member).as_posix(): member for member in archive
        }
        member = members.get("manifest.json")
        if member is None or not member.isfile():
            raise RecoveryError("Qdrant snapshot archive has no manifest")
        source = archive.extractfile(member)
        if source is None:
            raise RecoveryError("Qdrant snapshot manifest is unreadable")
        with source:
            manifest = json.load(source)
    if manifest.get("format_version") != FORMAT_VERSION:
        raise RecoveryError("Unsupported Qdrant snapshot format")
    collections = manifest.get("collections")
    if not isinstance(collections, list) or not collections:
        raise RecoveryError("Qdrant snapshot contains no collections")
    return manifest


def _sqlite_entries_in_directory(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(
        candidate for candidate in root.rglob("*") if candidate.is_file()
    ):
        if not _is_sqlite_candidate(path):
            continue
        entries.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "sqlite": _sqlite_summary(path),
            }
        )
    return entries


def _volume_sqlite_manifest(archive_path: Path) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="volume-manifest-") as temporary_dir:
        root = Path(temporary_dir)
        with tarfile.open(archive_path, mode="r:gz") as archive:
            _safe_extract_archive(archive, root)
        return _sqlite_entries_in_directory(root)


def normalize_volume_archive(source_archive: Path, output_archive: Path) -> int:
    """Replace SQLite files in a stopped-volume archive with API backups.

    The final archive preserves the original numeric ownership and modes while
    omitting SQLite journals that must not be replayed after a clean restore.
    """

    if not source_archive.is_file() or source_archive.is_symlink():
        raise RecoveryError("Volume snapshot archive is unavailable or unsafe")
    output_archive.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_archive.with_name(
        f".{output_archive.name}.{uuid.uuid4().hex}.tmp"
    )

    with tempfile.TemporaryDirectory(prefix="volume-normalize-") as temporary_dir:
        extracted_root = Path(temporary_dir) / "extracted"
        replacement_root = Path(temporary_dir) / "sqlite"
        members: list[tuple[Path, tarfile.TarInfo]] = []
        seen: set[Path] = set()
        with tarfile.open(source_archive, mode="r:gz") as source:
            extracted_root.mkdir(parents=True, exist_ok=True)
            for member in source:
                relative = _safe_archive_member(member)
                if relative == Path("."):
                    continue
                if relative in seen:
                    raise RecoveryError(
                        f"Duplicate archive member: {relative.as_posix()}"
                    )
                seen.add(relative)
                members.append((relative, copy.copy(member)))

                destination = extracted_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                extracted = source.extractfile(member)
                if extracted is None:
                    raise RecoveryError(
                        f"Could not read archive member: {member.name!r}"
                    )
                with extracted, destination.open("wb") as output:
                    shutil.copyfileobj(extracted, output, length=1024 * 1024)

        sidecars = {
            path.relative_to(extracted_root)
            for path in extracted_root.rglob("*")
            if path.is_file() and _sqlite_sidecar_primary(path) is not None
        }
        replacements: dict[Path, Path] = {}
        for path in sorted(
            candidate
            for candidate in extracted_root.rglob("*")
            if candidate.is_file()
            and candidate.relative_to(extracted_root) not in sidecars
        ):
            if not _is_sqlite_candidate(path):
                continue
            relative = path.relative_to(extracted_root)
            replacement = replacement_root / relative
            _sqlite_backup(path, replacement)
            replacements[relative] = replacement

        try:
            with tarfile.open(temporary_output, mode="w:gz") as destination:
                for relative, original in members:
                    if relative in sidecars:
                        continue
                    archive_member = copy.copy(original)
                    archive_member.name = relative.as_posix()
                    archive_member.pax_headers = {
                        key: value
                        for key, value in original.pax_headers.items()
                        if key not in {"path", "linkpath"}
                    }
                    if archive_member.isdir():
                        archive_member.size = 0
                        destination.addfile(archive_member)
                        continue
                    content = replacements.get(relative, extracted_root / relative)
                    archive_member.size = content.stat().st_size
                    archive_member.type = tarfile.REGTYPE
                    archive_member.linkname = ""
                    with content.open("rb") as stream:
                        destination.addfile(archive_member, stream)
            os.replace(temporary_output, output_archive)
        finally:
            temporary_output.unlink(missing_ok=True)
    return len(replacements)


def create_bundle_manifest(root: Path, env_file: Path) -> dict[str, Any]:
    root = root.resolve()
    application_manifest_path = root / "manifest/application.json"
    if not application_manifest_path.is_file():
        raise RecoveryError("Application snapshot manifest is missing")
    application_manifest = json.loads(
        application_manifest_path.read_text(encoding="utf-8")
    )

    qdrant_archive = root / "components/qdrant/qdrant-snapshots.tar.gz"
    if not qdrant_archive.is_file():
        raise RecoveryError("Qdrant snapshot archive is missing")
    qdrant_manifest = _read_qdrant_manifest(qdrant_archive)

    volume_sqlite: dict[str, list[dict[str, Any]]] = {}
    for component in REQUIRED_VOLUME_COMPONENTS:
        archive = root / f"components/volumes/{component}.tar.gz"
        if not archive.is_file():
            raise RecoveryError(f"{component} volume snapshot is missing")
        volume_sqlite[component] = _volume_sqlite_manifest(archive)

    entries = application_manifest.get("entries")
    if not isinstance(entries, list):
        raise RecoveryError("Application snapshot manifest is invalid")

    components = {
        component
        for entry in entries
        for component in entry.get("components", [])
        if isinstance(component, str)
    }
    components.update({"qdrant", *REQUIRED_VOLUME_COMPONENTS, "config-inventory"})
    required = {
        "application",
        "sqlite",
        "matrix",
        "qdrant",
        "prometheus",
        "grafana",
        "bisq2",
        "alertmanager",
        "config-inventory",
    }
    missing = sorted(required - components)
    if missing:
        raise RecoveryError(
            f"Required backup components are missing: {', '.join(missing)}"
        )

    artifacts = []
    for path in sorted(
        candidate for candidate in root.rglob("*") if candidate.is_file()
    ):
        if path == root / "manifest.json":
            continue
        relative = path.relative_to(root)
        artifacts.append(
            {
                "path": relative.as_posix(),
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )

    manifest = {
        "artifacts": artifacts,
        "components_available": sorted(components),
        "created_at": _now_iso(),
        "environment_variable_names": _environment_variable_names(env_file),
        "format_version": FORMAT_VERSION,
        "qdrant_collections": sorted(
            str(item["collection"]) for item in qdrant_manifest["collections"]
        ),
        "volume_sqlite": volume_sqlite,
    }
    _write_json(root / "manifest.json", manifest)
    return manifest


def _selected_components(raw_components: list[str]) -> set[str]:
    selected = set(raw_components or ["all"])
    allowed = {
        "all",
        "application",
        "sqlite",
        "matrix",
        "qdrant",
        "prometheus",
        "grafana",
        "bisq2",
        "alertmanager",
    }
    unknown = selected - allowed
    if unknown:
        raise RecoveryError(f"Unknown restore component: {', '.join(sorted(unknown))}")
    if "all" in selected:
        return allowed - {"all"}
    return selected


def _verify_artifacts(root: Path, manifest: dict[str, Any]) -> int:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise RecoveryError("Backup artifact manifest is empty")
    checked = 0
    for artifact in artifacts:
        relative = _safe_relative(str(artifact.get("path", "")))
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise RecoveryError(f"Backup artifact is missing: {relative.as_posix()}")
        if path.stat().st_size != int(artifact.get("size_bytes", -1)):
            raise RecoveryError(f"Backup artifact size mismatch: {relative.as_posix()}")
        if _sha256(path) != artifact.get("sha256"):
            raise RecoveryError(
                f"Backup artifact checksum mismatch: {relative.as_posix()}"
            )
        checked += 1
    return checked


def _load_application_manifest(root: Path) -> dict[str, Any]:
    path = root / "manifest/application.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError("Application snapshot manifest is unreadable") from exc
    if manifest.get("format_version") != FORMAT_VERSION:
        raise RecoveryError("Unsupported application snapshot format")
    if not isinstance(manifest.get("entries"), list):
        raise RecoveryError("Application snapshot entries are invalid")
    return manifest


def _entry_is_selected(entry: dict[str, Any], selected: set[str]) -> bool:
    components = entry.get("components")
    return isinstance(components, list) and bool(selected.intersection(components))


def _entry_file_metadata(entry: dict[str, Any]) -> tuple[int, int, int]:
    values = (entry.get("mode"), entry.get("uid"), entry.get("gid"))
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        raise RecoveryError("Application snapshot file metadata is invalid")
    mode, uid, gid = values
    if not 0 <= mode <= 0o777 or not 0 <= uid < 2**32 or not 0 <= gid < 2**32:
        raise RecoveryError("Application snapshot file metadata is out of range")
    return mode, uid, gid


def _apply_file_metadata(path: Path, metadata: tuple[int, int, int]) -> None:
    mode, uid, gid = metadata
    current = path.stat()
    if current.st_uid != uid or current.st_gid != gid:
        try:
            os.chown(path, uid, gid)
        except PermissionError as exc:
            raise RecoveryError(f"Could not restore ownership for {path.name}") from exc
    path.chmod(mode)


def _safe_destination(root: Path, relative: Path) -> Path:
    current = root
    for part in relative.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise RecoveryError(f"Refusing restore through symlink: {relative}")
    destination = root / relative
    resolved_parent = destination.parent.resolve()
    if resolved_parent != root and root not in resolved_parent.parents:
        raise RecoveryError(f"Restore target escapes data directory: {relative}")
    return destination


def _data_file_components(
    path: Path,
    relative: Path,
    matrix_state_paths: set[Path] | None,
) -> set[str]:
    matrix_state = _is_matrix_state(relative, matrix_state_paths)
    if _is_sqlite_candidate(path):
        components = {"sqlite"}
        if matrix_state:
            components.add("matrix")
        return components
    return {"matrix" if matrix_state else "application"}


def _record_restore_preimage(
    destination: Path,
    relative: Path,
    sqlite_file: bool,
    rollback_dir: Path,
    transaction_manifest: dict[str, Any],
) -> None:
    if destination.is_symlink():
        raise RecoveryError(f"Refusing to replace symlink: {relative}")

    rollback_path: Path | None = None
    original_metadata: tuple[int, int, int] | None = None
    if destination.exists():
        if not destination.is_file():
            raise RecoveryError(f"Restore target is not a file: {relative}")
        destination_stat = destination.stat()
        original_metadata = (
            stat.S_IMODE(destination_stat.st_mode) & 0o777,
            destination_stat.st_uid,
            destination_stat.st_gid,
        )
        rollback_path = rollback_dir / "files" / relative
        rollback_path.parent.mkdir(parents=True, exist_ok=True)
        if sqlite_file:
            _sqlite_backup(destination, rollback_path)
        else:
            shutil.copy2(destination, rollback_path)

    transaction_entry: dict[str, Any] = {
        "had_original": rollback_path is not None,
        "relative_path": relative.as_posix(),
        "sqlite": sqlite_file,
    }
    if rollback_path is not None and original_metadata is not None:
        transaction_entry["rollback_path"] = rollback_path.relative_to(
            rollback_dir
        ).as_posix()
        transaction_entry["metadata"] = {
            "gid": original_metadata[2],
            "mode": original_metadata[0],
            "uid": original_metadata[1],
        }
    entries = transaction_manifest["entries"]
    if not isinstance(entries, list):  # pragma: no cover - internal invariant
        raise RecoveryError("Application rollback manifest is invalid")
    entries.append(transaction_entry)
    _write_json(_rollback_manifest_path(rollback_dir), transaction_manifest)


def _remove_restored_data_file(destination: Path, sqlite_file: bool) -> None:
    destination.unlink()
    if sqlite_file:
        for suffix in SQLITE_SIDECAR_SUFFIXES:
            Path(f"{destination}{suffix}").unlink(missing_ok=True)


def _verify_application_restore(
    root: Path, scratch: Path, selected: set[str]
) -> tuple[int, int]:
    manifest = _load_application_manifest(root)
    restored_count = 0
    sqlite_count = 0
    for entry in manifest["entries"]:
        if not _entry_is_selected(entry, selected):
            continue
        storage = root / _safe_relative(str(entry.get("storage_path", "")))
        relative = _safe_relative(str(entry.get("relative_path", "")))
        _entry_file_metadata(entry)
        if not storage.is_file() or storage.is_symlink():
            raise RecoveryError(f"Application backup file is missing: {relative}")
        if _sha256(storage) != entry.get("sha256"):
            raise RecoveryError(f"Application backup checksum mismatch: {relative}")

        restored = scratch / "application-data" / relative
        restored.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(storage, restored)
        if entry.get("type") == "sqlite":
            sqlite_count += 1
            expected = entry.get("sqlite")
            actual = _sqlite_summary(restored)
            if not isinstance(expected, dict) or actual != expected:
                raise RecoveryError(f"SQLite row-count mismatch: {relative}")
        restored_count += 1
    return restored_count, sqlite_count


def _verify_volume_restore(
    root: Path,
    scratch: Path,
    selected: set[str],
    manifest: dict[str, Any],
) -> tuple[int, int]:
    checked_volumes = 0
    checked_sqlite = 0
    expected_by_component = manifest.get("volume_sqlite")
    if not isinstance(expected_by_component, dict):
        raise RecoveryError("Volume SQLite manifest is invalid")
    for component in REQUIRED_VOLUME_COMPONENTS:
        if component not in selected:
            continue
        archive_path = root / f"components/volumes/{component}.tar.gz"
        destination = scratch / "volumes" / component
        with tarfile.open(archive_path, mode="r:gz") as archive:
            _safe_extract_archive(archive, destination)
        actual_entries = _sqlite_entries_in_directory(destination)
        expected_entries = expected_by_component.get(component)
        if not isinstance(expected_entries, list) or actual_entries != expected_entries:
            raise RecoveryError(f"{component} volume SQLite row-count mismatch")
        checked_volumes += 1
        checked_sqlite += len(actual_entries)
    return checked_volumes, checked_sqlite


def _verify_qdrant_restore(root: Path, scratch: Path, selected: set[str]) -> int:
    if "qdrant" not in selected:
        return 0
    archive_path = root / "components/qdrant/qdrant-snapshots.tar.gz"
    destination = scratch / "qdrant"
    with tarfile.open(archive_path, mode="r:gz") as archive:
        _safe_extract_archive(archive, destination)
    manifest_path = destination / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError("Restored Qdrant manifest is unreadable") from exc
    if manifest.get("format_version") != FORMAT_VERSION:
        raise RecoveryError("Unsupported restored Qdrant format")
    collections = manifest.get("collections")
    if not isinstance(collections, list) or not collections:
        raise RecoveryError("Restored Qdrant snapshot has no collections")
    for entry in collections:
        snapshot = destination / _safe_relative(str(entry.get("file", "")))
        if not snapshot.is_file() or snapshot.stat().st_size != int(
            entry.get("size_bytes", -1)
        ):
            raise RecoveryError("Restored Qdrant collection snapshot is missing")
        if _sha256(snapshot) != entry.get("sha256"):
            raise RecoveryError("Restored Qdrant collection checksum mismatch")
    return len(collections)


def verify_bundle(
    snapshot_root: Path, scratch_root: Path, raw_components: list[str]
) -> dict[str, int]:
    snapshot_root = snapshot_root.resolve()
    scratch_root = scratch_root.resolve()
    manifest_path = snapshot_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError("Backup manifest is unreadable") from exc
    if manifest.get("format_version") != FORMAT_VERSION:
        raise RecoveryError("Unsupported backup format")

    variable_names = manifest.get("environment_variable_names")
    if not isinstance(variable_names, list) or any(
        not isinstance(name, str) or not ENV_NAME_RE.fullmatch(name)
        for name in variable_names
    ):
        raise RecoveryError("Environment inventory contains invalid data")

    selected = _selected_components(raw_components)
    scratch_root.mkdir(parents=True, exist_ok=True)
    artifact_count = _verify_artifacts(snapshot_root, manifest)
    application_count, sqlite_count = _verify_application_restore(
        snapshot_root, scratch_root, selected
    )
    volume_count, volume_sqlite_count = _verify_volume_restore(
        snapshot_root, scratch_root, selected, manifest
    )
    qdrant_count = _verify_qdrant_restore(snapshot_root, scratch_root, selected)
    if "qdrant" in selected:
        expected_collections = manifest.get("qdrant_collections")
        qdrant_manifest = json.loads(
            (scratch_root / "qdrant" / "manifest.json").read_text(encoding="utf-8")
        )
        actual_collections = sorted(
            str(entry.get("collection", ""))
            for entry in qdrant_manifest.get("collections", [])
        )
        if expected_collections != actual_collections:
            raise RecoveryError("Qdrant collection inventory mismatch")
    return {
        "application_files": application_count,
        "artifacts": artifact_count,
        "qdrant_collections": qdrant_count,
        "sqlite_databases": sqlite_count + volume_sqlite_count,
        "volumes": volume_count,
    }


def _rollback_manifest_path(rollback_dir: Path) -> Path:
    return rollback_dir / "rollback-manifest.json"


def rollback_data(data_dir: Path, rollback_dir: Path) -> int:
    data_dir = data_dir.resolve()
    rollback_dir = rollback_dir.resolve()
    manifest_path = _rollback_manifest_path(rollback_dir)
    if not manifest_path.exists():
        return 0
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError("Application rollback manifest is unreadable") from exc
    if manifest.get("format_version") != FORMAT_VERSION or not isinstance(
        manifest.get("entries"), list
    ):
        raise RecoveryError("Application rollback manifest is invalid")

    rolled_back = 0
    for entry in reversed(manifest["entries"]):
        relative = _safe_relative(str(entry.get("relative_path", "")))
        destination = _safe_destination(data_dir, relative)
        if destination.is_symlink():
            raise RecoveryError(f"Refusing rollback through symlink: {relative}")
        sqlite_file = entry.get("sqlite") is True
        if entry.get("had_original") is True:
            rollback_relative = _safe_relative(str(entry.get("rollback_path", "")))
            source = rollback_dir / rollback_relative
            if not source.is_file() or source.is_symlink():
                raise RecoveryError(f"Application rollback file is missing: {relative}")
            metadata_value = entry.get("metadata")
            if not isinstance(metadata_value, dict):
                raise RecoveryError("Application rollback metadata is invalid")
            metadata = _entry_file_metadata(metadata_value)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(
                f".{destination.name}.{uuid.uuid4().hex}.rollback"
            )
            try:
                shutil.copy2(source, temporary)
                _apply_file_metadata(temporary, metadata)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            destination.unlink(missing_ok=True)
        if sqlite_file:
            for suffix in SQLITE_SIDECAR_SUFFIXES:
                Path(f"{destination}{suffix}").unlink(missing_ok=True)
        rolled_back += 1
    manifest_path.unlink()
    return rolled_back


def restore_data(
    snapshot_root: Path,
    data_dir: Path,
    rollback_dir: Path,
    raw_components: list[str],
    matrix_state_paths: set[Path] | None = None,
) -> int:
    selected = _selected_components(raw_components).intersection(
        {"application", "sqlite", "matrix"}
    )
    snapshot_root = snapshot_root.resolve()
    data_dir = data_dir.resolve()
    rollback_dir = rollback_dir.resolve()
    if rollback_dir == data_dir or data_dir in rollback_dir.parents:
        raise RecoveryError("Rollback directory must be outside application data")
    manifest = _load_application_manifest(snapshot_root)
    effective_matrix_paths = set(matrix_state_paths or set())
    for entry in manifest["entries"]:
        components = entry.get("components")
        if not isinstance(components, list) or "matrix" not in components:
            continue
        matrix_relative = _safe_relative(str(entry.get("relative_path", "")))
        effective_matrix_paths.add(matrix_relative)
        if matrix_relative.parent != Path("."):
            effective_matrix_paths.add(matrix_relative.parent)
    selected_entries = [
        entry for entry in manifest["entries"] if _entry_is_selected(entry, selected)
    ]
    expected_paths: set[Path] = set()
    for entry in selected_entries:
        relative = _safe_relative(str(entry.get("relative_path", "")))
        if relative in expected_paths:
            raise RecoveryError(f"Duplicate application snapshot path: {relative}")
        expected_paths.add(relative)
    data_dir.mkdir(parents=True, exist_ok=True)
    rollback_dir.mkdir(parents=True, exist_ok=True)

    transaction_entries: list[dict[str, Any]] = []
    transaction_manifest = {
        "entries": transaction_entries,
        "format_version": FORMAT_VERSION,
    }
    _write_json(_rollback_manifest_path(rollback_dir), transaction_manifest)
    try:
        for current, relative in list(_iter_data_files(data_dir)):
            if relative in expected_paths:
                continue
            components = _data_file_components(
                current,
                relative,
                effective_matrix_paths,
            )
            if not selected.intersection(components):
                continue
            destination = _safe_destination(data_dir, relative)
            sqlite_file = "sqlite" in components
            _record_restore_preimage(
                destination,
                relative,
                sqlite_file,
                rollback_dir,
                transaction_manifest,
            )
            _remove_restored_data_file(destination, sqlite_file)

        for entry in selected_entries:
            relative = _safe_relative(str(entry.get("relative_path", "")))
            source = snapshot_root / _safe_relative(str(entry.get("storage_path", "")))
            if not source.is_file() or source.is_symlink():
                raise RecoveryError(f"Restore source is unavailable: {relative}")
            destination = _safe_destination(data_dir, relative)
            if destination.is_symlink():
                raise RecoveryError(f"Refusing to replace symlink: {relative}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            sqlite_file = entry.get("type") == "sqlite"
            restore_metadata = _entry_file_metadata(entry)
            _record_restore_preimage(
                destination,
                relative,
                sqlite_file,
                rollback_dir,
                transaction_manifest,
            )

            temporary = destination.with_name(
                f".{destination.name}.{uuid.uuid4().hex}.restore"
            )
            try:
                shutil.copy2(source, temporary)
                if _sha256(temporary) != entry.get("sha256"):
                    raise RecoveryError(f"Restore checksum mismatch: {relative}")
                if sqlite_file:
                    expected = entry.get("sqlite")
                    if _sqlite_summary(temporary) != expected:
                        raise RecoveryError(f"Restore row-count mismatch: {relative}")
                _apply_file_metadata(temporary, restore_metadata)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            if sqlite_file:
                for suffix in SQLITE_SIDECAR_SUFFIXES:
                    Path(f"{destination}{suffix}").unlink(missing_ok=True)
    except Exception:
        rollback_data(data_dir, rollback_dir)
        raise
    return len(selected_entries)


def backup_file(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise RecoveryError("Backup source is unavailable or unsafe")
    if destination.is_symlink():
        raise RecoveryError("Backup destination is unsafe")
    if _is_sqlite_candidate(source):
        _sqlite_backup(source, destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _qdrant_settings() -> tuple[str, int, str | None, str]:
    host = os.environ.get("QDRANT_HOST", "qdrant")
    port = int(os.environ.get("QDRANT_PORT", "6333"))
    api_key = os.environ.get("QDRANT_API_KEY") or None
    scheme = os.environ.get("QDRANT_SCHEME", "http").lower()
    if scheme not in {"http", "https"}:
        raise RecoveryError("Unsupported Qdrant URL scheme")
    return host, port, api_key, scheme


def _qdrant_headers() -> dict[str, str]:
    _host, _port, api_key, _scheme = _qdrant_settings()
    headers = {"Accept": "application/json"}
    if api_key:
        headers["api-key"] = api_key
    return headers


def _qdrant_url(path: str) -> str:
    host, port, _api_key, scheme = _qdrant_settings()
    return f"{scheme}://{host}:{port}{path}"


def _qdrant_json(method: str, path: str, timeout: float = 120) -> dict[str, Any]:
    request = urllib.request.Request(
        _qdrant_url(path),
        data=b"" if method in {"POST", "PUT", "DELETE"} else None,
        headers=_qdrant_headers(),
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        raise RecoveryError(f"Qdrant {method} request failed") from exc
    if not isinstance(payload, dict):
        raise RecoveryError("Qdrant returned an invalid response")
    return payload


def _qdrant_collections(*, allow_empty: bool = False) -> list[str]:
    payload = _qdrant_json("GET", "/collections")
    result = payload.get("result")
    rows = result.get("collections") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise RecoveryError("Qdrant collection list is invalid")
    if any(
        not isinstance(row, dict)
        or not isinstance(row.get("name"), str)
        or not row["name"]
        for row in rows
    ):
        raise RecoveryError("Qdrant collection entry is invalid")
    collections = sorted(str(row["name"]) for row in rows)
    if not collections and not allow_empty:
        raise RecoveryError("Qdrant contains no collections to back up")
    if len(collections) != len(set(collections)):
        raise RecoveryError("Qdrant returned duplicate collections")
    return collections


def _download_qdrant_snapshot(
    collection: str, snapshot_name: str, destination: Path
) -> None:
    collection_path = urllib.parse.quote(collection, safe="")
    snapshot_path = urllib.parse.quote(snapshot_name, safe="")
    request = urllib.request.Request(
        _qdrant_url(f"/collections/{collection_path}/snapshots/{snapshot_path}"),
        headers=_qdrant_headers(),
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            with destination.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
    except urllib.error.URLError as exc:
        destination.unlink(missing_ok=True)
        raise RecoveryError("Could not download Qdrant snapshot") from exc


def wait_for_qdrant(timeout: float) -> None:
    if timeout <= 0:
        raise RecoveryError("Qdrant wait timeout must be positive")
    deadline = time.monotonic() + timeout
    while True:
        try:
            payload = _qdrant_json("GET", "/collections", timeout=2)
            result = payload.get("result")
            if isinstance(result, dict) and isinstance(result.get("collections"), list):
                return
        except RecoveryError:
            pass
        if time.monotonic() >= deadline:
            raise RecoveryError("Timed out waiting for scratch Qdrant")
        time.sleep(0.5)


def export_qdrant(output: BinaryIO, *, allow_empty: bool = False) -> None:
    with tempfile.TemporaryDirectory(prefix="qdrant-backup-") as temporary_dir:
        root = Path(temporary_dir)
        manifest_entries: list[dict[str, Any]] = []
        for index, collection in enumerate(
            _qdrant_collections(allow_empty=allow_empty)
        ):
            collection_path = urllib.parse.quote(collection, safe="")
            created = _qdrant_json("POST", f"/collections/{collection_path}/snapshots")
            result = created.get("result")
            snapshot_name = result.get("name") if isinstance(result, dict) else None
            if not isinstance(snapshot_name, str) or not snapshot_name:
                raise RecoveryError("Qdrant did not return a snapshot name")

            destination = root / f"collection-{index}.snapshot"
            try:
                _download_qdrant_snapshot(collection, snapshot_name, destination)
            finally:
                snapshot_path = urllib.parse.quote(snapshot_name, safe="")
                _qdrant_json(
                    "DELETE",
                    f"/collections/{collection_path}/snapshots/{snapshot_path}",
                )
            if destination.stat().st_size == 0:
                raise RecoveryError("Qdrant produced an empty snapshot")
            manifest_entries.append(
                {
                    "collection": collection,
                    "file": destination.name,
                    "sha256": _sha256(destination),
                    "size_bytes": destination.stat().st_size,
                }
            )

        manifest_bytes = (
            json.dumps(
                {
                    "collections": manifest_entries,
                    "created_at": _now_iso(),
                    "format_version": FORMAT_VERSION,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        with tarfile.open(fileobj=output, mode="w|gz") as archive:
            manifest_info = tarfile.TarInfo("manifest.json")
            manifest_info.size = len(manifest_bytes)
            manifest_info.mode = 0o600
            archive.addfile(manifest_info, io.BytesIO(manifest_bytes))
            for entry in manifest_entries:
                archive.add(
                    root / entry["file"], arcname=entry["file"], recursive=False
                )


def _upload_qdrant_snapshot(collection: str, snapshot: Path) -> None:
    host, port, api_key, scheme = _qdrant_settings()
    boundary = f"bisq-support-{uuid.uuid4().hex}"
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="snapshot"; '
        'filename="collection.snapshot"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("ascii")
    suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
    content_length = len(prefix) + snapshot.stat().st_size + len(suffix)
    connection_class = (
        http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_class(host, port, timeout=600)
    collection_path = urllib.parse.quote(collection, safe="")
    path = f"/collections/{collection_path}/snapshots/upload?priority=snapshot"
    headers = {
        "Accept": "application/json",
        "Content-Length": str(content_length),
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    if api_key:
        headers["api-key"] = api_key
    try:
        connection.putrequest("POST", path)
        for name, value in headers.items():
            connection.putheader(name, value)
        connection.endheaders()
        connection.send(prefix)
        with snapshot.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                connection.send(chunk)
        connection.send(suffix)
        response = connection.getresponse()
        payload = response.read()
        if not 200 <= response.status < 300:
            raise RecoveryError(
                f"Qdrant snapshot restore failed with status {response.status}"
            )
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RecoveryError("Qdrant restore response was not JSON") from exc
        if not isinstance(decoded, dict):
            raise RecoveryError("Qdrant restore response was invalid")
        if decoded.get("result") is not True:
            raise RecoveryError("Qdrant did not confirm snapshot restore")
    finally:
        connection.close()


def import_qdrant(
    input_stream: BinaryIO,
    selected_collection: str | None,
    *,
    delete_absent: bool = False,
) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="qdrant-restore-") as temporary_dir:
        root = Path(temporary_dir)
        with tarfile.open(fileobj=input_stream, mode="r|gz") as archive:
            _safe_extract_archive(archive, root)
        try:
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RecoveryError("Qdrant restore manifest is unreadable") from exc
        if manifest.get("format_version") != FORMAT_VERSION:
            raise RecoveryError("Unsupported Qdrant restore format")
        entries = manifest.get("collections")
        if not isinstance(entries, list) or (not entries and not delete_absent):
            raise RecoveryError("Qdrant restore archive has no collections")

        restored: list[str] = []
        for entry in entries:
            collection_value = entry.get("collection")
            if not isinstance(collection_value, str) or not collection_value:
                raise RecoveryError("Qdrant restore collection is invalid")
            collection = collection_value
            if selected_collection and collection != selected_collection:
                continue
            snapshot = root / _safe_relative(str(entry.get("file", "")))
            if (
                not snapshot.is_file()
                or snapshot.stat().st_size != int(entry.get("size_bytes", -1))
                or _sha256(snapshot) != entry.get("sha256")
            ):
                raise RecoveryError("Qdrant restore snapshot checksum mismatch")
            _upload_qdrant_snapshot(collection, snapshot)
            restored.append(collection)

        if selected_collection and not restored:
            raise RecoveryError("Requested Qdrant collection is absent from backup")
        current_collections = set(_qdrant_collections(allow_empty=True))
        missing = set(restored) - current_collections
        if missing:
            raise RecoveryError("Restored Qdrant collection is not present")
        if delete_absent:
            expected = {
                str(entry["collection"])
                for entry in entries
                if isinstance(entry, dict)
                and isinstance(entry.get("collection"), str)
                and entry["collection"]
            }
            for collection in sorted(current_collections - expected):
                collection_path = urllib.parse.quote(collection, safe="")
                _qdrant_json("DELETE", f"/collections/{collection_path}")
            if set(_qdrant_collections(allow_empty=True)) != expected:
                raise RecoveryError("Qdrant collection rollback inventory mismatch")
        return restored


def extract_stream(destination: Path) -> int:
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as archive:
        return len(_safe_extract_archive(archive, destination))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot_parser = subparsers.add_parser("snapshot-data")
    snapshot_parser.add_argument("--data-dir", type=Path, required=True)
    snapshot_parser.add_argument("--output-dir", type=Path, required=True)
    snapshot_parser.add_argument("--env-file", type=Path)
    snapshot_parser.add_argument("--matrix-state-path", action="append", default=[])

    manifest_parser = subparsers.add_parser("create-manifest")
    manifest_parser.add_argument("--root", type=Path, required=True)
    manifest_parser.add_argument("--env-file", type=Path, required=True)

    verify_parser = subparsers.add_parser("verify-bundle")
    verify_parser.add_argument("--snapshot-root", type=Path, required=True)
    verify_parser.add_argument("--scratch-root", type=Path, required=True)
    verify_parser.add_argument("--component", action="append", default=[])

    restore_parser = subparsers.add_parser("restore-data")
    restore_parser.add_argument("--snapshot-root", type=Path, required=True)
    restore_parser.add_argument("--data-dir", type=Path, required=True)
    restore_parser.add_argument("--rollback-dir", type=Path, required=True)
    restore_parser.add_argument("--component", action="append", default=[])
    restore_parser.add_argument("--matrix-state-path", action="append", default=[])

    rollback_parser = subparsers.add_parser("rollback-data")
    rollback_parser.add_argument("--data-dir", type=Path, required=True)
    rollback_parser.add_argument("--rollback-dir", type=Path, required=True)

    file_parser = subparsers.add_parser("backup-file")
    file_parser.add_argument("source", type=Path)
    file_parser.add_argument("destination", type=Path)

    volume_parser = subparsers.add_parser("normalize-volume")
    volume_parser.add_argument("--input", type=Path, required=True)
    volume_parser.add_argument("--output", type=Path, required=True)

    qdrant_export_parser = subparsers.add_parser("qdrant-export")
    qdrant_export_parser.add_argument("--allow-empty", action="store_true")
    qdrant_import_parser = subparsers.add_parser("qdrant-import")
    qdrant_import_parser.add_argument("--collection")
    qdrant_import_parser.add_argument("--delete-absent", action="store_true")
    qdrant_wait_parser = subparsers.add_parser("qdrant-wait")
    qdrant_wait_parser.add_argument("--timeout", type=float, default=60)

    extract_parser = subparsers.add_parser("extract-stream")
    extract_parser.add_argument("--destination", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "snapshot-data":
            matrix_paths = (
                matrix_state_paths_from_env(args.env_file) if args.env_file else None
            )
            if args.matrix_state_path:
                if matrix_paths is None:
                    matrix_paths = set()
                matrix_paths.update(
                    matrix_state_paths_from_values(args.matrix_state_path)
                )
            manifest = snapshot_data(
                args.data_dir,
                args.output_dir,
                matrix_state_paths=matrix_paths,
            )
            print(json.dumps({"files": len(manifest["entries"])}, sort_keys=True))
        elif args.command == "create-manifest":
            manifest = create_bundle_manifest(args.root, args.env_file)
            print(
                json.dumps(
                    {"components": manifest["components_available"]}, sort_keys=True
                )
            )
        elif args.command == "verify-bundle":
            print(
                json.dumps(
                    verify_bundle(
                        args.snapshot_root, args.scratch_root, args.component
                    ),
                    sort_keys=True,
                )
            )
        elif args.command == "restore-data":
            matrix_paths = (
                matrix_state_paths_from_values(args.matrix_state_path)
                if args.matrix_state_path
                else None
            )
            restored = restore_data(
                args.snapshot_root,
                args.data_dir,
                args.rollback_dir,
                args.component,
                matrix_state_paths=matrix_paths,
            )
            print(json.dumps({"restored_files": restored}, sort_keys=True))
        elif args.command == "rollback-data":
            rolled_back = rollback_data(args.data_dir, args.rollback_dir)
            print(json.dumps({"rolled_back_files": rolled_back}, sort_keys=True))
        elif args.command == "backup-file":
            backup_file(args.source, args.destination)
        elif args.command == "normalize-volume":
            print(
                json.dumps(
                    {
                        "sqlite_databases": normalize_volume_archive(
                            args.input, args.output
                        )
                    },
                    sort_keys=True,
                )
            )
        elif args.command == "qdrant-export":
            export_qdrant(sys.stdout.buffer, allow_empty=args.allow_empty)
        elif args.command == "qdrant-import":
            print(
                json.dumps(
                    {
                        "restored_collections": import_qdrant(
                            sys.stdin.buffer,
                            args.collection,
                            delete_absent=args.delete_absent,
                        )
                    },
                    sort_keys=True,
                )
            )
        elif args.command == "qdrant-wait":
            wait_for_qdrant(args.timeout)
            print(json.dumps({"ready": True}))
        elif args.command == "extract-stream":
            print(json.dumps({"extracted": extract_stream(args.destination)}))
        else:  # pragma: no cover - argparse enforces a command
            raise RecoveryError("Unknown command")
    except (OSError, RecoveryError, ValueError, tarfile.TarError) as exc:
        print(f"disaster recovery error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

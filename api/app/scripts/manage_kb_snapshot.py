#!/usr/bin/env python3
"""Create, restore, and verify frozen knowledge-base snapshots for retrieval evals.

The retrieval stack depends on a small set of authoritative inputs:
- wiki/processed_wiki.jsonl
- faqs.db
- bm25_vocabulary.json
- qdrant_index_metadata.json

This script snapshots those files into a versioned directory, records checksums,
and can later restore/verify them for reproducible benchmark runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Keep import behavior aligned with other scripts in this repo.
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from app.core.config import get_settings  # noqa: E402

DEFAULT_SNAPSHOT_DIR_NAME = "evaluation/kb_snapshots"
MANIFEST_FILENAME = "manifest.json"


@dataclass(frozen=True)
class SnapshotFileSpec:
    relative_path: str
    required: bool
    capture_mode: str  # "copy" | "sqlite_backup"


SNAPSHOT_FILE_SPECS: tuple[SnapshotFileSpec, ...] = (
    SnapshotFileSpec("wiki/processed_wiki.jsonl", required=True, capture_mode="copy"),
    SnapshotFileSpec(
        "wiki/payment_methods_reference.jsonl", required=False, capture_mode="copy"
    ),
    SnapshotFileSpec("faqs.db", required=True, capture_mode="sqlite_backup"),
    SnapshotFileSpec("bm25_vocabulary.json", required=True, capture_mode="copy"),
    SnapshotFileSpec("qdrant_index_metadata.json", required=False, capture_mode="copy"),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _detect_git_ref() -> dict[str, str | None]:
    def _run(cmd: list[str]) -> str | None:
        try:
            completed = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
            return completed.stdout.strip() or None
        except Exception:
            return None

    return {
        "commit": _run(["git", "rev-parse", "HEAD"]),
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
    }


def _resolve_data_dir(data_dir_arg: str | None) -> Path:
    if data_dir_arg:
        return Path(data_dir_arg).expanduser().resolve()

    settings = get_settings()
    return Path(settings.DATA_DIR).expanduser().resolve()


def _resolve_snapshot_root(snapshot_root_arg: str | None, *, data_dir: Path) -> Path:
    if snapshot_root_arg:
        return Path(snapshot_root_arg).expanduser().resolve()
    return (data_dir / DEFAULT_SNAPSHOT_DIR_NAME).resolve()


def _safe_relpath(rel_path: str) -> Path:
    p = Path(rel_path)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"Invalid relative path in manifest/spec: {rel_path}")
    return p


def _sqlite_backup(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as src_conn:
        with sqlite3.connect(dst) as dst_conn:
            src_conn.backup(dst_conn)
    # Snapshot should be a single deterministic DB file.
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(dst) + suffix)
        if sidecar.exists():
            sidecar.unlink()


def _sqlite_logical_sha256(path: Path) -> str:
    """Hash SQLite logical content (schema + rows) for stable comparisons."""
    hasher = hashlib.sha256()
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        for line in conn.iterdump():
            hasher.update(line.encode("utf-8"))
            hasher.update(b"\n")
    return hasher.hexdigest()


def create_snapshot(args: argparse.Namespace) -> int:
    data_dir = _resolve_data_dir(args.data_dir)
    snapshot_root = _resolve_snapshot_root(args.snapshot_root, data_dir=data_dir)
    snapshot_dir = snapshot_root / args.name

    if snapshot_dir.exists() and not args.force:
        print(f"Snapshot already exists: {snapshot_dir}")
        print("Use --force to overwrite.")
        return 2

    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)

    files_dir = snapshot_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    manifest_files: list[dict[str, Any]] = []
    missing_required: list[str] = []
    copied_count = 0

    for spec in SNAPSHOT_FILE_SPECS:
        rel = _safe_relpath(spec.relative_path)
        src = data_dir / rel
        dst = files_dir / rel

        if not src.exists():
            if spec.required:
                missing_required.append(spec.relative_path)
            continue

        if spec.capture_mode == "sqlite_backup":
            _sqlite_backup(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        st = dst.stat()
        row: dict[str, Any] = {
            "relative_path": spec.relative_path,
            "required": spec.required,
            "capture_mode": spec.capture_mode,
            "source_path": str(src),
            "snapshot_path": str(dst),
            "size": st.st_size,
            "mtime": st.st_mtime,
            "sha256": _sha256(dst),
        }
        if spec.capture_mode == "sqlite_backup":
            row["source_logical_sha256"] = _sqlite_logical_sha256(src)
            row["snapshot_logical_sha256"] = _sqlite_logical_sha256(dst)
        manifest_files.append(row)
        copied_count += 1

    if missing_required:
        print("Missing required files, snapshot aborted:")
        for path in missing_required:
            print(f"  - {path}")
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        return 2

    manifest: dict[str, Any] = {
        "snapshot_name": args.name,
        "created_at": _now_iso(),
        "note": args.note or "",
        "data_dir": str(data_dir),
        "git": _detect_git_ref(),
        "retrieval_inputs": [spec.relative_path for spec in SNAPSHOT_FILE_SPECS],
        "files": manifest_files,
        "restore_notes": [
            "Restore this snapshot before benchmark runs for comparable metrics.",
            "After restore, rebuild Qdrant index if collection contents may differ.",
        ],
    }

    manifest_path = snapshot_dir / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Created snapshot: {snapshot_dir}")
    print(f"Manifest: {manifest_path}")
    print(f"Files captured: {copied_count}")
    return 0


def _resolve_snapshot_dir(snapshot_root: Path, snapshot_arg: str) -> Path:
    direct = Path(snapshot_arg).expanduser().resolve()
    if direct.exists():
        return direct

    from_root = (snapshot_root / snapshot_arg).resolve()
    if from_root.exists():
        return from_root

    raise FileNotFoundError(f"Snapshot not found as path or name: {snapshot_arg}")


def _load_manifest(snapshot_dir: Path) -> dict[str, Any]:
    manifest_path = snapshot_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    with manifest_path.open(encoding="utf-8") as f:
        return json.load(f)


def restore_snapshot(args: argparse.Namespace) -> int:
    data_dir = _resolve_data_dir(args.data_dir)
    snapshot_root = _resolve_snapshot_root(args.snapshot_root, data_dir=data_dir)
    snapshot_dir = _resolve_snapshot_dir(snapshot_root, args.snapshot)
    manifest = _load_manifest(snapshot_dir)

    files = manifest.get("files") or []
    if not isinstance(files, list):
        print("Invalid manifest: 'files' must be a list")
        return 2

    backup_dir = None
    if args.backup_existing:
        backup_dir = (
            snapshot_dir / f"restore_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        backup_dir.mkdir(parents=True, exist_ok=True)

    restored = 0
    for entry in files:
        rel_raw = entry.get("relative_path", "")
        rel = _safe_relpath(str(rel_raw))
        src = snapshot_dir / "files" / rel
        dst = data_dir / rel

        if not src.exists():
            print(f"Skipping missing snapshot file: {src}")
            continue

        if args.dry_run:
            print(f"[dry-run] restore {src} -> {dst}")
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)

        if backup_dir is not None and dst.exists():
            backup_target = backup_dir / rel
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, backup_target)

        shutil.copy2(src, dst)
        restored += 1

    print(f"Restored files: {restored}")
    if backup_dir is not None:
        print(f"Backup of previous files: {backup_dir}")
    return 0


def verify_snapshot(args: argparse.Namespace) -> int:
    data_dir = _resolve_data_dir(args.data_dir)
    snapshot_root = _resolve_snapshot_root(args.snapshot_root, data_dir=data_dir)
    snapshot_dir = _resolve_snapshot_dir(snapshot_root, args.snapshot)
    manifest = _load_manifest(snapshot_dir)

    files = manifest.get("files") or []
    mismatches: list[str] = []
    checked = 0

    for entry in files:
        rel = _safe_relpath(str(entry.get("relative_path", "")))
        expected_sha = str(entry.get("sha256", ""))
        capture_mode = str(entry.get("capture_mode", "copy"))
        target = data_dir / rel
        checked += 1

        if not target.exists():
            mismatches.append(f"missing: {rel}")
            continue

        if capture_mode == "sqlite_backup" and entry.get("source_logical_sha256"):
            expected_logical = str(entry.get("source_logical_sha256"))
            actual_logical = _sqlite_logical_sha256(target)
            if actual_logical != expected_logical:
                mismatches.append(
                    "logical sqlite mismatch: "
                    f"{rel} expected={expected_logical[:12]} actual={actual_logical[:12]}"
                )
        else:
            actual_sha = _sha256(target)
            if expected_sha and actual_sha != expected_sha:
                mismatches.append(
                    "sha mismatch: "
                    f"{rel} expected={expected_sha[:12]} actual={actual_sha[:12]}"
                )

    print(f"Checked files: {checked}")
    if mismatches:
        print("Snapshot verification failed:")
        for item in mismatches:
            print(f"  - {item}")
        return 1

    print("Snapshot verification passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage frozen retrieval knowledge-base snapshots"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a KB snapshot")
    create.add_argument("--name", required=True, help="Snapshot name")
    create.add_argument("--data-dir", default=None, help="DATA_DIR override")
    create.add_argument(
        "--snapshot-root",
        default=None,
        help="Snapshot root dir (default: <DATA_DIR>/evaluation/kb_snapshots)",
    )
    create.add_argument("--note", default="", help="Optional note in manifest")
    create.add_argument(
        "--force", action="store_true", help="Overwrite existing snapshot"
    )

    restore = subparsers.add_parser("restore", help="Restore files from a snapshot")
    restore.add_argument(
        "--snapshot",
        required=True,
        help="Snapshot name under root or absolute snapshot path",
    )
    restore.add_argument("--data-dir", default=None, help="DATA_DIR override")
    restore.add_argument(
        "--snapshot-root",
        default=None,
        help="Snapshot root dir (default: <DATA_DIR>/evaluation/kb_snapshots)",
    )
    restore.add_argument("--dry-run", action="store_true", help="Print actions only")
    restore.add_argument(
        "--backup-existing",
        action="store_true",
        help="Backup overwritten files under the snapshot directory",
    )

    verify = subparsers.add_parser("verify", help="Verify DATA_DIR against a snapshot")
    verify.add_argument(
        "--snapshot",
        required=True,
        help="Snapshot name under root or absolute snapshot path",
    )
    verify.add_argument("--data-dir", default=None, help="DATA_DIR override")
    verify.add_argument(
        "--snapshot-root",
        default=None,
        help="Snapshot root dir (default: <DATA_DIR>/evaluation/kb_snapshots)",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "create":
        return create_snapshot(args)
    if args.command == "restore":
        return restore_snapshot(args)
    if args.command == "verify":
        return verify_snapshot(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

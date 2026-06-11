from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

from app.scripts.manage_kb_snapshot import (
    MANIFEST_FILENAME,
    create_snapshot,
    restore_snapshot,
    verify_snapshot,
)


def _args(**overrides: object) -> argparse.Namespace:
    values = {
        "name": "test-snapshot",
        "snapshot": "test-snapshot",
        "data_dir": None,
        "snapshot_root": None,
        "note": "",
        "force": False,
        "dry_run": False,
        "backup_existing": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _write_required_inputs(data_dir: Path) -> None:
    wiki_dir = data_dir / "wiki"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "processed_wiki.jsonl").write_text(
        '{"title":"Test","content":"wiki"}\n',
        encoding="utf-8",
    )
    (data_dir / "bm25_vocabulary.json").write_text("{}", encoding="utf-8")

    with sqlite3.connect(data_dir / "faqs.db") as conn:
        conn.execute("CREATE TABLE faqs (id INTEGER PRIMARY KEY, question TEXT)")
        conn.execute("INSERT INTO faqs (question) VALUES ('How?')")


def test_kb_snapshot_captures_verifies_and_restores_llm_wiki_tree(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    snapshot_root = tmp_path / "snapshots"
    _write_required_inputs(data_dir)

    page = data_dir / "knowledge" / "llm_wiki" / "pages" / "bisq-easy.md"
    page.parent.mkdir(parents=True)
    page.write_text("# Bisq Easy\n\nReviewed content.\n", encoding="utf-8")

    create_result = create_snapshot(
        _args(data_dir=str(data_dir), snapshot_root=str(snapshot_root))
    )

    assert create_result == 0
    snapshot_dir = snapshot_root / "test-snapshot"
    manifest = json.loads((snapshot_dir / MANIFEST_FILENAME).read_text())
    llm_wiki_entry = next(
        item
        for item in manifest["files"]
        if item["relative_path"] == "knowledge/llm_wiki"
    )
    assert llm_wiki_entry["capture_mode"] == "copy_tree"
    assert llm_wiki_entry["size"] == len(page.read_bytes())
    assert (
        snapshot_dir / "files" / "knowledge" / "llm_wiki" / "pages" / "bisq-easy.md"
    ).exists()

    assert (
        verify_snapshot(
            _args(
                snapshot="test-snapshot",
                data_dir=str(data_dir),
                snapshot_root=str(snapshot_root),
            )
        )
        == 0
    )

    llm_wiki_dir = data_dir / "knowledge" / "llm_wiki"
    shutil.rmtree(llm_wiki_dir)
    llm_wiki_dir.write_text(
        "stale file where restored tree belongs\n", encoding="utf-8"
    )
    assert (
        verify_snapshot(
            _args(
                snapshot="test-snapshot",
                data_dir=str(data_dir),
                snapshot_root=str(snapshot_root),
            )
        )
        == 1
    )

    assert (
        restore_snapshot(
            _args(
                snapshot="test-snapshot",
                data_dir=str(data_dir),
                snapshot_root=str(snapshot_root),
            )
        )
        == 0
    )
    assert llm_wiki_dir.is_dir()
    assert page.read_text(encoding="utf-8") == "# Bisq Easy\n\nReviewed content.\n"
    assert (
        verify_snapshot(
            _args(
                snapshot="test-snapshot",
                data_dir=str(data_dir),
                snapshot_root=str(snapshot_root),
            )
        )
        == 0
    )

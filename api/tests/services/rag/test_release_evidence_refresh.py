"""Offline orchestration regressions; source extraction is covered separately."""

import argparse
import hashlib
import json
from types import SimpleNamespace

import pytest
from app.scripts import refresh_release_evidence as refresh
from app.services.rag.code_evidence import CodeEvidenceLoader, CodeEvidenceRecord
from app.services.rag.release_notes import ReleaseNote, ReleaseNotesLoader


def setup_preparation(tmp_path, monkeypatch, missing_body):
    cache = tmp_path / "discovery"
    cache.mkdir()
    for repo, versions in [
        ("bisq", ["1.10.8", "1.10.7", "1.10.6"]),
        ("bisq2", ["2.1.13", "2.1.12", "2.1.11"]),
    ]:
        (tmp_path / repo).mkdir()
        rows = [
            {
                "tag_name": "v" + version,
                "draft": False,
                "prerelease": False,
                "published_at": "2026-09-01T00:00:00Z",
                "html_url": f"https://github.com/bisq-network/{repo}/releases/tag/v{version}",
                "body": "Official fixture release notes",
            }
            for version in versions
        ]
        if repo == "bisq":
            rows[0]["body"] = missing_body
        (cache / f"{repo}.json").write_text(json.dumps(rows))
    commits = {}

    def git(path, *args):
        if args[0] == "status":
            return ""
        if args[0] == "checkout":
            commits[path] = hashlib.sha1(args[-1].encode()).hexdigest()
            return ""
        assert args == ("rev-parse", "HEAD")
        return commits[path]

    class Extractor:
        def __init__(self, **kwargs):
            self.options = kwargs

        def extract(self):
            repo, tag, commit = (
                self.options[key] for key in ("repo", "release_tag", "commit")
            )
            names = sorted(
                refresh.REQUIRED_BISQ1 if repo == "bisq" else refresh.REQUIRED_BISQ2
            )
            if repo == "bisq":
                names.append("fixture-mediation")
            return [
                CodeEvidenceRecord.from_dict(
                    {
                        "id": f"{repo}:{commit[:12]}:{name}",
                        "type": "code_fact",
                        "repo": repo,
                        "commit": commit,
                        "path": "src/Fixture.java",
                        "line_start": 1,
                        "line_end": 1,
                        "symbol": (
                            refresh.BISQ1_SYMBOL
                            if name == "fixture-mediation"
                            else name
                        ),
                        "protocol": "multisig_v1" if repo == "bisq" else "bisq_easy",
                        "audience": "staff_only",
                        "freshness_class": "release_bound",
                        "risk_level": "low",
                        "claim": "Fixture source claim.",
                        "support_use": "Fixture only.",
                        "source_refs": [f"code:{repo}@{commit}:src/Fixture.java:1-1"],
                        "release_tag": tag,
                        "applies_to_versions": [tag[1:]],
                        "source_sha256": "f" * 64,
                    }
                )
                for name in names
            ]

    monkeypatch.setattr(refresh, "_git", git)
    monkeypatch.setattr(refresh, "CodeEvidenceExtractor", Extractor)
    monkeypatch.setattr(
        refresh,
        "CodeEvidenceFreshnessChecker",
        lambda path: SimpleNamespace(check=lambda rows: SimpleNamespace(stale=0)),
    )
    return argparse.Namespace(
        output=tmp_path / "output",
        bisq_checkout=tmp_path / "bisq",
        bisq2_checkout=tmp_path / "bisq2",
        previous_code=None,
        previous_notes=None,
        discovery_cache=cache,
        offline=True,
    )


@pytest.mark.parametrize("body", [None, "", " \n "])
def test_missing_upstream_notes_preserve_code_and_record_gap(
    tmp_path, monkeypatch, body
):
    args = setup_preparation(tmp_path, monkeypatch, body)
    manifest = refresh.prepare(args)
    code = CodeEvidenceLoader(args.output / "code_evidence.jsonl").load()
    notes = ReleaseNotesLoader(args.output / "release_notes.jsonl").load()
    assert manifest["code_records"] == len(code) == 30
    assert manifest["release_notes"] == len(notes) == 5
    gap = next(
        row
        for row in manifest["coverage"]
        if row["repo"] == "bisq" and row["tag"] == "v1.10.8"
    )
    assert gap["code_records"] == 6
    assert gap["notes_status"] == "missing_upstream_body"
    assert gap["notes_sha256"] is None
    assert all((note.repo, note.tag) != ("bisq", "v1.10.8") for note in notes)
    assert all(
        row["notes_status"] == "available"
        for row in manifest["coverage"]
        if row is not gap
    )


def test_missing_notes_do_not_relabel_retained_body_as_current(tmp_path, monkeypatch):
    args = setup_preparation(tmp_path, monkeypatch, None)
    previous = tmp_path / "previous-notes.jsonl"

    def retained(tag):
        body = "Earlier reviewed official body"
        return ReleaseNote.from_dict(
            {
                "repo": "bisq",
                "tag": tag,
                "commit": hashlib.sha1(tag.encode()).hexdigest(),
                "published_at": "2026-08-01T00:00:00Z",
                "url": f"https://github.com/bisq-network/bisq/releases/tag/{tag}",
                "body": body,
                "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
            }
        )

    previous.write_text(
        "".join(
            json.dumps(retained(tag).to_dict()) + "\n" for tag in ["v1.10.8", "v1.9.99"]
        )
    )
    original = previous.read_bytes()
    args.previous_notes = previous
    refresh.prepare(args)
    notes = ReleaseNotesLoader(args.output / "release_notes.jsonl").load()
    assert any(note.tag == "v1.9.99" for note in notes)
    assert not any(note.tag == "v1.10.8" for note in notes)
    assert previous.read_bytes() == original


def test_malformed_nontext_body_still_fails_closed(tmp_path, monkeypatch):
    args = setup_preparation(tmp_path, monkeypatch, {"unexpected": "object"})
    with pytest.raises(ValueError, match="must be text or absent"):
        refresh.prepare(args)
    assert not args.output.exists()

import hashlib
import json

import pytest
from app.scripts.refresh_release_evidence import stable_releases
from app.services.rag.release_notes import ReleaseNote, ReleaseNotesLoader


def note(
    repo="bisq",
    tag="v1.10.8",
    body="## Reliability\n\nMediation payout handling changed.\n\n## Other\n\nUI changes.",
):
    return {
        "repo": repo,
        "tag": tag,
        "commit": "a" * 40,
        "published_at": "2026-09-16T14:57:35Z",
        "url": f"https://github.com/bisq-network/{repo}/releases/tag/{tag}",
        "body": body,
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
    }


def loader(tmp_path, rows):
    path = tmp_path / "release_notes.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return ReleaseNotesLoader(path)


@pytest.mark.parametrize(
    "changes",
    [
        {"url": "https://github.com/attacker/bisq/releases/tag/v1.10.8"},
        {"url": "https://github.com/bisq-network/bisq/releases/tag/v1.10.7"},
        {"repo": "bisq2"},
        {"commit": "main"},
        {"body": "Changed after hash"},
        {"published_at": "2026-09-16"},
        {"tag": "v1.10.8-rc.1"},
    ],
)
def test_rejects_wrong_authority_version_and_corrupt_snapshot(changes):
    with pytest.raises(ValueError):
        ReleaseNote.from_dict({**note(), **changes})


def test_runtime_product_version_filter_and_unknown_version_scope(tmp_path):
    data = loader(tmp_path, [note(tag="v1.10.7"), note(), note("bisq2", "v2.1.13")])
    latest = data.retrieve("Bisq 1 mediation failed")
    assert len(latest) == 1 and latest[0]["source_version"] == "1.10.8"
    assert latest[0]["user_version"] is None
    assert "not the user's installed version" in latest[0]["limitation"]
    older = data.retrieve("mediation failed", product="bisq1", user_version="1.10.7")
    assert len(older) == 1 and older[0]["source_version"] == "1.10.7"
    assert (
        data.retrieve("mediation failed", product="bisq1", user_version="2.1.13") == []
    )
    assert data.retrieve("mediation failed") == []


def test_bounded_relevance_excerpt_preserves_body_hash(tmp_path):
    body = "## Mediation\n\n" + "Mediation detail. " * 1500
    row = note(body=body)
    results = loader(tmp_path, [row]).retrieve("Bisq 1 mediation")
    assert len(results[0]["body"]) <= 6000
    assert results[0]["body_sha256"] == row["body_sha256"]
    assert results[0]["excerpt"] is True


def test_rejects_oversize_or_duplicate_snapshot(tmp_path):
    with pytest.raises(ValueError):
        ReleaseNote.from_dict(note(body="a" * 65537))
    with pytest.raises(ValueError, match="duplicate"):
        loader(tmp_path, [note(), note()]).load()


def test_discovery_last_three_stable_not_first_three_api_rows():
    rows = [
        {
            **note(tag="v1.10." + str(n)),
            "tag_name": "v1.10." + str(n),
            "html_url": note(tag="v1.10." + str(n))["url"],
            "draft": False,
            "prerelease": False,
        }
        for n in [7, 9, 6, 8]
    ]
    rows.append({"draft": True})
    assert [r["tag_name"] for r in stable_releases(rows, "bisq")] == [
        "v1.10.9",
        "v1.10.8",
        "v1.10.7",
    ]
    with pytest.raises(ValueError):
        stable_releases(rows[:2], "bisq")

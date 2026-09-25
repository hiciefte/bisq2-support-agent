"""Public guides require an exact, explicit review of a restricted projection."""

import sqlite3
from contextlib import closing

import pytest
from app.services.public_knowledge_service import PublicKnowledgeService

PAGE = """---
id: synthetic-guide
title: Synthetic support guide
type: llm_wiki
status: reviewed
protocol: bisq_easy
source_refs:
- https://bisq.wiki/Support
---
## Canonical Support Answer
Check the displayed connection status.

## Applies When
Bisq Easy reports a connection problem.

## Review Notes
PRIVATE reviewer case details.

## Evidence / Sources
PRIVATE source bibliography is not claim proof.

## Last Change Summary
PRIVATE staff discussion.
"""


@pytest.fixture
def guide_service(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    path = pages / "guide.md"
    path.write_text(PAGE)
    return PublicKnowledgeService(pages, tmp_path / "knowledge.db"), path


def test_review_publish_edit_revoke_keeps_one_page_and_audit(guide_service):
    service, path = guide_service
    original = path.read_bytes()
    assert service.get_public_projection("synthetic-guide") is None
    private = service.get_internal_page("synthetic-guide")
    assert "PRIVATE" in private["body"]
    assert "PRIVATE" not in str(private["projection"])
    assert not private["publication_history"]
    service.publish("synthetic-guide", private["projection"]["revision"], "reviewer")
    public = service.get_public_projection("synthetic-guide")
    assert [s["id"] for s in public["sections"]] == [
        "canonical-support-answer",
        "applies-when",
    ]
    assert "source_refs" not in public
    assert "reviewer" not in public
    assert path.read_bytes() == original

    path.write_text(PAGE.replace("displayed connection", "current connection"))
    assert service.get_public_projection("synthetic-guide") is None
    with pytest.raises(ValueError):
        service.publish("synthetic-guide", public["revision"], "reviewer")
    refreshed = service.get_internal_page("synthetic-guide")
    service.publish("synthetic-guide", refreshed["projection"]["revision"], "reviewer")
    service.revoke("synthetic-guide", "reviewer")
    assert service.get_public_projection("synthetic-guide") is None
    assert [
        e["action"]
        for e in service.get_internal_page("synthetic-guide")["publication_history"]
    ] == ["revoke", "publish", "publish"]
    with closing(sqlite3.connect(service.db_path)) as conn:
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'faqs'"
        ).fetchall()


@pytest.mark.parametrize(
    "change",
    [
        lambda text: text.replace("status: reviewed", "status: proposed"),
        lambda text: text.replace("## Applies When", "## Review-only applicability"),
        lambda text: text + "\n## Canonical Support Answer\nDuplicate answer\n",
    ],
)
def test_invalid_or_unreviewed_projection_cannot_publish(guide_service, change):
    service, path = guide_service
    path.write_text(change(PAGE))
    private = service.get_internal_page("synthetic-guide")
    assert not private["can_publish"]
    assert service.get_public_projection("synthetic-guide") is None
    with pytest.raises(ValueError):
        service.publish("synthetic-guide", "a" * 64, "reviewer")


def test_traversal_symlink_and_duplicate_page_are_not_public(guide_service, tmp_path):
    service, path = guide_service
    revision = service.get_internal_page("synthetic-guide")["projection"]["revision"]
    service.publish("synthetic-guide", revision, "reviewer")
    assert service.get_public_projection("../synthetic-guide") is None
    duplicate = path.with_name("duplicate.md")
    duplicate.write_text(PAGE)
    assert service.get_public_projection("synthetic-guide") is None
    duplicate.unlink()
    outside = tmp_path / "outside.md"
    path.rename(outside)
    path.symlink_to(outside)
    assert service.get_public_projection("synthetic-guide") is None


def test_revoke_survives_missing_current_page(guide_service):
    service, path = guide_service
    revision = service.get_internal_page("synthetic-guide")["projection"]["revision"]
    service.publish("synthetic-guide", revision, "reviewer")
    path.unlink()
    service.revoke("synthetic-guide", "reviewer")
    path.write_text(PAGE)
    assert service.get_public_projection("synthetic-guide") is None


def test_unrelated_invalid_yaml_does_not_break_review(guide_service):
    service, path = guide_service
    (path.parent / "broken.md").write_text("---\nid: [broken\n---\ninvalid")
    assert service.get_internal_page("synthetic-guide")["page_id"] == "synthetic-guide"


def test_changed_projection_approval_can_be_revoked_before_revert(guide_service):
    service, path = guide_service
    revision = service.get_internal_page("synthetic-guide")["projection"]["revision"]
    service.publish("synthetic-guide", revision, "reviewer")
    path.write_text(PAGE.replace("displayed connection", "current connection"))
    view = service.get_internal_page("synthetic-guide")
    assert not view["public"]
    assert view["publication_history"][0]["action"] == "publish"
    service.revoke("synthetic-guide", "reviewer")
    path.write_text(PAGE)
    assert service.get_public_projection("synthetic-guide") is None

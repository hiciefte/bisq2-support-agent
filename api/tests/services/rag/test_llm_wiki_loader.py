from pathlib import Path

from app.services.rag.llm_wiki_loader import LLMWikiLoader


def _write_playbook(
    directory: Path,
    name: str,
    *,
    status: str = "reviewed",
    page_id: str = "bisq-easy-reputation",
    source_refs: str = "- wiki:bisq-easy\n- faq:123",
    body: str = "## Canonical Support Answer\nUse Bisq Easy reputation carefully.",
) -> Path:
    path = directory / name
    path.write_text(
        f"""---
id: {page_id}
title: Bisq Easy reputation basics
type: llm_wiki
page_type: support_playbook
status: {status}
protocol: bisq_easy
reviewed_by: support-admin
reviewed_at: "2026-05-12"
risk_level: medium
source_refs:
{source_refs}
---
{body}
""",
        encoding="utf-8",
    )
    return path


def test_loader_indexes_only_reviewed_playbooks(tmp_path: Path) -> None:
    _write_playbook(tmp_path, "reviewed.md", status="reviewed")
    _write_playbook(tmp_path, "draft.md", status="draft", page_id="draft-reputation")

    docs = LLMWikiLoader().load_documents(tmp_path)

    assert len(docs) == 1
    doc = docs[0]
    assert doc.page_content.startswith("Support Playbook: Bisq Easy reputation basics")
    assert "Page type:" not in doc.page_content
    assert "Canonical Support Answer" in doc.page_content
    assert "Source refs:" in doc.page_content
    assert doc.metadata["id"] == "bisq-easy-reputation"
    assert doc.metadata["title"] == "Bisq Easy reputation basics"
    assert doc.metadata["type"] == "llm_wiki"
    assert doc.metadata["page_type"] == "support_playbook"
    assert doc.metadata["protocol"] == "bisq_easy"
    assert doc.metadata["status"] == "reviewed"
    assert doc.metadata["source_refs"] == ["wiki:bisq-easy", "faq:123"]
    assert doc.metadata["source_weight"] == 1.25


def test_loader_excludes_admin_only_sections_from_page_content(
    tmp_path: Path,
) -> None:
    _write_playbook(
        tmp_path,
        "reviewed.md",
        body="""## Canonical Support Answer
Use Bisq Easy reputation carefully.

## Applies When
- User asks about reputation in Bisq Easy.

## Do Not Say
- Do not claim buyers need reputation.

## Evidence / Sources
- `wiki:bisq-easy`

## Review Notes
- Reviewer correction: Removed unsupported advice.
- Future generator guidance: Do not overstate reputation requirements.

## Last Change Summary
Narrowed the canonical answer and added a guardrail.
""",
    )

    docs = LLMWikiLoader().load_documents(tmp_path)

    assert len(docs) == 1
    page_content = docs[0].page_content
    assert "Canonical Support Answer" in page_content
    assert "Use Bisq Easy reputation carefully." in page_content
    assert "Applies When" in page_content
    assert "Do Not Say" in page_content
    assert "Evidence / Sources" in page_content
    assert "Source refs:" in page_content
    assert "Review Notes" not in page_content
    assert "Reviewer correction" not in page_content
    assert "Future generator guidance" not in page_content
    assert "Last Change Summary" not in page_content
    assert "Narrowed the canonical answer" not in page_content


def test_loader_skips_reviewed_page_with_only_admin_only_body(
    tmp_path: Path,
) -> None:
    _write_playbook(
        tmp_path,
        "admin-only.md",
        body="""## Review Notes
- Reviewer correction: This page needs canonical content.

## Last Change Summary
Created by mistake without answer-facing content.
""",
    )

    docs = LLMWikiLoader().load_documents(tmp_path)

    assert docs == []


def test_loader_indexes_active_pages(tmp_path: Path) -> None:
    _write_playbook(tmp_path, "active.md", status="active")

    docs = LLMWikiLoader().load_documents(tmp_path)

    assert len(docs) == 1
    assert docs[0].metadata["status"] == "active"


def test_loader_skips_proposed_pages(tmp_path: Path) -> None:
    _write_playbook(tmp_path, "proposed.md", status="proposed")

    docs = LLMWikiLoader().load_documents(tmp_path)

    assert docs == []


def test_loader_skips_reviewed_page_without_source_refs(tmp_path: Path) -> None:
    _write_playbook(tmp_path, "unsupported.md", source_refs="")

    docs = LLMWikiLoader().load_documents(tmp_path)

    assert docs == []


def test_loader_skips_reviewed_page_with_mapping_source_refs(tmp_path: Path) -> None:
    _write_playbook(
        tmp_path,
        "mapping-source-refs.md",
        source_refs="  wiki: bisq-easy\n  faq: 123",
    )

    docs = LLMWikiLoader().load_documents(tmp_path)

    assert docs == []


def test_loader_uses_configured_llm_wiki_weight(tmp_path: Path) -> None:
    _write_playbook(tmp_path, "reviewed.md")
    loader = LLMWikiLoader(source_weights={"llm_wiki": 1.1})

    loader.update_source_weights({"llm_wiki": 1.18, "wiki": 0.9})

    docs = loader.load_documents(tmp_path)
    assert docs[0].metadata["source_weight"] == 1.18


def test_loader_rejects_duplicate_page_ids(tmp_path: Path) -> None:
    _write_playbook(tmp_path, "first.md", page_id="same-id")
    _write_playbook(tmp_path, "second.md", page_id="same-id")

    try:
        LLMWikiLoader().load_documents(tmp_path)
    except ValueError as exc:
        assert "duplicate LLM Wiki page id: same-id" in str(exc)
    else:
        raise AssertionError("duplicate page IDs should fail fast")

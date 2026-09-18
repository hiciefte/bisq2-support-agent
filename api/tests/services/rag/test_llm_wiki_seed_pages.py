import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml
from app.services.rag.llm_wiki_loader import LLMWikiLoader
from app.services.rag.source_refs import is_precise_code_source_ref


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    raw_frontmatter = text.split("---\n", 2)[1]
    parsed = yaml.safe_load(raw_frontmatter) or {}
    assert isinstance(parsed, dict)
    return parsed


def test_reviewed_llm_wiki_seed_pages_are_indexable_without_admin_sections() -> None:
    pages_dir = _repo_root() / "api" / "data" / "knowledge" / "llm_wiki" / "pages"
    pages = sorted(pages_dir.rglob("*.md"))
    assert pages, "Expected committed LLM Wiki seed pages"

    indexable_pages = []
    for page in pages:
        frontmatter = _frontmatter(page)
        assert frontmatter["status"] in {"reviewed", "active", "deprecated"}, page.name
        if frontmatter["status"] == "deprecated":
            continue
        indexable_pages.append(page)
        assert frontmatter.get("reviewed_by"), page.name
        assert frontmatter.get("reviewed_at"), page.name
        assert frontmatter.get("source_refs"), page.name

    documents = LLMWikiLoader().load_documents(pages_dir)
    assert len(documents) == len(indexable_pages)
    for document in documents:
        assert "## Review Notes" not in document.page_content
        assert "## Last Change Summary" not in document.page_content
        assert document.metadata.get("reviewed_by")
        assert document.metadata.get("reviewed_at")


def test_seed_pages_do_not_reference_stale_local_faq_1147() -> None:
    pages_dir = _repo_root() / "api" / "data" / "knowledge" / "llm_wiki" / "pages"
    combined = "\n".join(
        page.read_text(encoding="utf-8") for page in pages_dir.glob("*.md")
    )

    assert "faq:1147" not in combined


def test_seed_pages_use_durable_resolvable_sources() -> None:
    repo = _repo_root()
    pages_dir = repo / "api" / "data" / "knowledge" / "llm_wiki" / "pages"
    wiki_titles = _wiki_titles(repo / "api" / "data" / "wiki")
    faq_refs = _faq_refs(repo / "api" / "data" / "faqs.db")
    failures = []

    for page in sorted(pages_dir.glob("*.md")):
        frontmatter = _frontmatter(page)
        for source_ref in frontmatter.get("source_refs") or []:
            source_ref = str(source_ref)
            if source_ref.startswith("wiki:"):
                if source_ref.removeprefix("wiki:") not in wiki_titles:
                    failures.append(f"{page.name}: missing wiki source {source_ref}")
            elif source_ref.startswith("faq:"):
                if (
                    faq_refs is not None
                    and source_ref.removeprefix("faq:") not in faq_refs
                ):
                    failures.append(f"{page.name}: missing FAQ source {source_ref}")
            elif source_ref.startswith("llm_wiki:"):
                continue
            elif _is_primary_https_source(source_ref) or is_precise_code_source_ref(
                source_ref
            ):
                continue
            else:
                failures.append(f"{page.name}: non-durable source {source_ref}")

    assert (
        failures == []
    ), f"First 10 failures: {failures[:10]} (total: {len(failures)})"


def test_faq_refs_handles_missing_or_empty_fixture(tmp_path: Path) -> None:
    missing_db = tmp_path / "missing-faqs.db"
    empty_db = tmp_path / "empty-faqs.db"
    sqlite3.connect(empty_db).close()

    assert _faq_refs(missing_db) is None
    assert _faq_refs(empty_db) is None


def _wiki_titles(wiki_dir: Path) -> set[str]:
    titles: set[str] = set()
    for path in sorted(wiki_dir.glob("*.jsonl")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AssertionError(
                    f"Invalid JSONL in {path.name}:{line_number}: {exc}"
                ) from exc
            title = str(row.get("title") or "").strip()
            if title:
                titles.add(title)
    return titles


def _faq_refs(db_path: Path) -> set[str] | None:
    if not db_path.exists():
        return None

    with sqlite3.connect(db_path) as conn:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'faqs'"
        ).fetchone()
        if table_exists is None:
            return None
        rows = conn.execute("SELECT id, slug FROM faqs").fetchall()

    refs = {str(row[0]) for row in rows}
    refs.update(str(row[1]) for row in rows if row[1])
    return refs


# Reviewed public primary origins, not an arbitrary URL acceptance rule. This
# offline check validates provenance shape; it does not assert live availability
# or that the cited document actually supports every claim in a seed page.
# Ordinary HTTPS navigation refs may be mutable (like wiki: aliases). Only
# formal code: refs claim precise revision/line evidence under source_refs.py.
_PRIMARY_DOC_ORIGINS = {
    "bisq.wiki",
    "bisq.network",
    "bitcoin.org",
    "developer.bitcoin.org",
    "docs.oracle.com",
    "learn.microsoft.com",
    "support.microsoft.com",
    "devblogs.microsoft.com",
    "www.gnupg.org",
    "www.usps.com",
    "digprjsurvey.amazon.co.uk",
    "community.start9.com",
}
_PRIMARY_GITHUB_REPOS = {
    "bisq-network/bisq",
    "bisq-network/bisq2",
    "bisq-network/bitcoinj",
    "Start9-Community/bisq-startos",
    "mempool/mempool",
    "dutu/run-on-tails",
}


def _is_primary_https_source(ref: str) -> bool:
    if any(char.isspace() for char in ref) or "\\" in ref:
        return False
    try:
        url = urlsplit(ref)
        if (
            url.scheme != "https"
            or url.username
            or url.password
            or url.port
            or url.query
            or "%" in url.path
            or any(part in {".", ".."} for part in url.path.split("/"))
        ):
            return False
    except ValueError:
        return False
    if url.hostname == "github.com":
        parts = url.path.strip("/").split("/")
        if len(parts) < 3 or "/".join(parts[:2]) not in _PRIMARY_GITHUB_REPOS:
            return False
        tail = "/".join(parts[2:])
        return bool(
            re.fullmatch(
                r"(?:blob/(?:[a-fA-F0-9]{40}|main|master|v[0-9][^/]*)/.+|commit/[a-fA-F0-9]{40}|"
                r"releases/tag/v[0-9][^/]*|(?:issues|pull)/[1-9][0-9]*|issues)",
                tail,
            )
        )
    if url.hostname == "mempool.space":
        return url.path == "/" and not url.fragment
    if url.hostname not in _PRIMARY_DOC_ORIGINS or not url.path.strip("/"):
        return False
    return not any(
        part.lower().startswith(("special:", "user:", "user_talk:"))
        or part.lower() in {"login", "search", "account", "admin"}
        for part in url.path.split("/")
    )


@pytest.mark.parametrize(
    "ref",
    [
        "https://bisq.wiki/Resyncing_SPV_file#Fix_an_Incomplete_SPV_Resync",
        "https://docs.oracle.com/en/java/javase/21/docs/specs/man/java.html",
        "https://github.com/bisq-network/bisq/blob/"
        + "a" * 40
        + "/core/Example.java#L1-L4",
        "https://github.com/bisq-network/bisq/releases/tag/v1.10.8",
        "https://github.com/bisq-network/bisq2/issues/2587#issuecomment-2276260039",
        "https://community.start9.com/t/restoring-history-from-account-on-laptop-to-bisq-on-start9/2138",
        "https://mempool.space/",
        "https://github.com/bisq-network/bisq/blob/main/core/File.java",
        "https://github.com/bisq-network/bisq/blob/master/docs/build.md",
        "https://github.com/bisq-network/bisq/blob/v1.10.8/core/File.java",
    ],
)
def test_primary_https_sources_accept_reviewed_documentation_and_source_links(ref):
    assert _is_primary_https_source(ref)


@pytest.mark.parametrize(
    "ref",
    [
        "support:private-room:message",
        "http://bisq.wiki/Wallet",
        "https://localhost/Wallet",
        "https://127.0.0.1/Wallet",
        "https://example.onion/Wallet",
        "https://pastebin.com/private-paste",
        "https://bisq.wiki.attacker.example/Wallet",
        "https://secret@bisq.wiki/Wallet",
        "https://bisq.wiki:8443/Wallet",
        "https://bisq.wiki/Wallet?token=private",
        "https://bisq.wiki/Special:UserLogin",
        "https://bisq.wiki/User:Someone",
        "https://bisq.wiki/../private",
        "https://bisq.wiki/%2e%2e/private",
        "https://bisq.wiki/Wallet\n",
        "https://bisq.wiki/",
        "https://mempool.space/tx/private",
        "https://github.com/unreviewed/project/blob/" + "a" * 40 + "/file.py",
        "https://github.com/bisq-network/bisq/blob/abcdef/core/File.java",
        "https://github.com/bisq-network/bisq",
    ],
)
def test_primary_https_sources_reject_private_and_ambiguous_refs(ref):
    assert not _is_primary_https_source(ref)


@pytest.mark.parametrize(
    "ref,valid",
    [
        ("code:bisq@abcdef:core/File.java:1-4", True),
        ("code:bisq@main:core/File.java:1-4", False),
        ("code:bisq@abcdef:core/File.java:4-1", False),
    ],
)
def test_seed_code_refs_follow_shared_precision_contract(ref, valid):
    assert is_precise_code_source_ref(ref) is valid


def test_live_source_url_does_not_claim_formal_code_precision():
    live_url = "https://github.com/bisq-network/bisq/blob/main/core/File.java"
    assert _is_primary_https_source(live_url)
    assert not is_precise_code_source_ref(live_url)
    assert not is_precise_code_source_ref("code:bisq@main:core/File.java:1-4")

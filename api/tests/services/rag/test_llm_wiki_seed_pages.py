import json
import sqlite3
from pathlib import Path

import yaml
from app.services.rag.llm_wiki_loader import LLMWikiLoader


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    raw_frontmatter = text.split("---\n", 2)[1]
    parsed = yaml.safe_load(raw_frontmatter) or {}
    assert isinstance(parsed, dict)
    return parsed


def test_initial_llm_wiki_seed_pages_require_human_review() -> None:
    pages_dir = _repo_root() / "api" / "data" / "knowledge" / "llm_wiki" / "pages"
    pages = sorted(pages_dir.glob("*.md"))
    assert pages, "Expected committed LLM Wiki seed pages"

    for page in pages:
        frontmatter = _frontmatter(page)
        assert frontmatter["status"] in {"proposed", "deprecated"}, page.name
        assert frontmatter.get("reviewed_by") is None, page.name
        assert frontmatter.get("reviewed_at") is None, page.name

    assert LLMWikiLoader().load_documents(pages_dir) == []


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
            else:
                failures.append(f"{page.name}: non-durable source {source_ref}")

    assert failures == []


def test_faq_refs_handles_missing_or_empty_fixture(tmp_path: Path) -> None:
    missing_db = tmp_path / "missing-faqs.db"
    empty_db = tmp_path / "empty-faqs.db"
    sqlite3.connect(empty_db).close()

    assert _faq_refs(missing_db) is None
    assert _faq_refs(empty_db) is None


def _wiki_titles(wiki_dir: Path) -> set[str]:
    titles: set[str] = set()
    for path in sorted(wiki_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            title = str(row.get("title") or "").strip()
            if title:
                titles.add(title)
    return titles


def _faq_refs(db_path: Path) -> set[str] | None:
    if not db_path.exists():
        return None

    conn = sqlite3.connect(db_path)
    try:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'faqs'"
        ).fetchone()
        if table_exists is None:
            return None
        rows = conn.execute("SELECT id, slug FROM faqs").fetchall()
    finally:
        conn.close()

    refs = {str(row[0]) for row in rows}
    refs.update(str(row[1]) for row in rows if row[1])
    return refs

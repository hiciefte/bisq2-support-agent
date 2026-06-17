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

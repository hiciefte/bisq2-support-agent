"""Import externally reviewed LLM Wiki markdown batches.

The normal online workflow is the Knowledge Updates admin approval flow. This
importer exists for offline review batches: it normalizes returned markdown,
mines the human edit deltas into generator feedback, and verifies that the
resulting pages are loadable by the same LLM Wiki loader used for RAG indexing.
"""

from __future__ import annotations

import difflib
import json
import re
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from app.services.knowledge_updates.llm_wiki_update_service import (
    SECTION_ORDER,
    KnowledgeUpdateService,
    _compose_markdown,
    _durable_source_refs,
    _read_markdown_text,
    _section_diff_summary,
    _section_text_from_markdown,
    _string_list,
)
from app.services.rag.llm_wiki_loader import (
    LLM_WIKI_TYPE,
    REVIEWED_STATUS,
    LLMWikiLoader,
)

ADMIN_SECTION_NAMES = ("Review Notes", "Last Change Summary")
COPY_EDIT_SIGNALS = {
    "custory",
    "deffinitely",
    "ficed",
    "linke",
    "netowork",
    "outllook",
    "sellinig",
    "tablooks",
    "walle",
}
SOURCE_SENSITIVE_RE = re.compile(
    r"("
    r"\b\d+(?:\.\d+)?\s*(?:hour|hours|day|days|minute|minutes|btc|bsq|sat|sats|%)\b"
    r"|%USERPROFILE%"
    r"|\bAppData\b"
    r"|~/"
    r"|/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
    r"|\\[A-Za-z0-9_.-]+\\"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReviewedLLMWikiPageImportResult:
    page_id: str
    title: str
    filename: str
    original_path: str
    reviewed_path: str
    protocol: str
    source_refs: List[str]
    normalized_markdown: str
    changed_sections: List[str]
    section_diff_summary: List[Dict[str, Any]]
    feedback_tags: List[str]
    future_generator_note: Optional[str]
    issues: List[str]
    source_sensitive_additions: List[str]
    review_notes: Optional[str]
    last_change_summary: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewedLLMWikiBatchImportResult:
    matched_count: int
    loader_document_count: int
    missing_originals: List[str]
    invalid_pages: List[str]
    admin_section_leakage: List[str]
    pages: List[ReviewedLLMWikiPageImportResult]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ReviewedLLMWikiBatchImporter:
    """Normalize a reviewed LLM Wiki batch and mine its human edits."""

    def __init__(
        self,
        *,
        original_pages_dir: str | Path,
        knowledge_update_service: Optional[KnowledgeUpdateService] = None,
        loader: Optional[LLMWikiLoader] = None,
    ):
        self.original_pages_dir = Path(original_pages_dir)
        self.knowledge_update_service = knowledge_update_service
        self.loader = loader or LLMWikiLoader()

    def import_batch(
        self,
        *,
        reviewed_path: str | Path,
        reviewer: str,
        reviewed_at: str,
        output_dir: Optional[str | Path] = None,
        apply: bool = False,
        record_feedback: bool = True,
    ) -> ReviewedLLMWikiBatchImportResult:
        reviewed_path = Path(reviewed_path)
        reviewer = str(reviewer).strip()
        reviewed_at = str(reviewed_at).strip()
        if not reviewer:
            raise ValueError("reviewer is required")
        if not reviewed_at:
            raise ValueError("reviewed_at is required")

        output_root = (
            Path(output_dir) if output_dir is not None else self.original_pages_dir
        )
        originals = self._original_page_index()
        pages: List[ReviewedLLMWikiPageImportResult] = []
        missing_originals: List[str] = []
        invalid_pages: List[str] = []

        with _reviewed_markdown_dir(reviewed_path) as reviewed_root:
            for reviewed_file in sorted(reviewed_root.rglob("*.md")):
                relative_name = str(reviewed_file.relative_to(reviewed_root))
                reviewed_text = reviewed_file.read_text(encoding="utf-8")
                reviewed = _read_markdown_text(reviewed_text, path=reviewed_file)
                if reviewed is None:
                    invalid_pages.append(relative_name)
                    continue

                page_id = str(reviewed.frontmatter.get("id") or "").strip()
                original_path = originals.by_filename.get(
                    reviewed_file.name
                ) or originals.by_page_id.get(page_id)
                if original_path is None:
                    missing_originals.append(relative_name)
                    continue

                original_text = original_path.read_text(encoding="utf-8")
                original = _read_markdown_text(original_text, path=original_path)
                if original is None:
                    invalid_pages.append(str(original_path))
                    continue

                result = _build_page_result(
                    original_path=original_path,
                    original_text=original_text,
                    original_frontmatter=original.frontmatter,
                    original_body=original.body,
                    reviewed_file=reviewed_file,
                    reviewed_text=reviewed_text,
                    reviewed_frontmatter=reviewed.frontmatter,
                    reviewed_body=reviewed.body,
                    reviewer=reviewer,
                    reviewed_at=reviewed_at,
                )
                pages.append(result)

                if apply:
                    target = output_root / reviewed_file.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(result.normalized_markdown, encoding="utf-8")

                if self.knowledge_update_service is not None and record_feedback:
                    self.knowledge_update_service.record_external_review_feedback(
                        target_page_id=result.page_id,
                        target_page_title=result.title,
                        page_path=str(original_path),
                        reviewed_by=reviewer,
                        reviewed_at=reviewed_at,
                        review_notes=result.review_notes,
                        last_change_summary=result.last_change_summary,
                        feedback_tags=result.feedback_tags,
                        future_generator_note=result.future_generator_note,
                        section_diff_summary=result.section_diff_summary,
                        protocol=result.protocol,
                        source_refs=result.source_refs,
                        original_markdown=original_text,
                        reviewed_markdown=reviewed_text,
                        normalized_markdown=result.normalized_markdown,
                        issues=result.issues,
                        source_batch_id=reviewed_path.name,
                    )

            loader_document_count, admin_section_leakage = self._validate_loader_output(
                pages=pages,
                output_root=output_root,
                use_applied_output=apply,
            )

        return ReviewedLLMWikiBatchImportResult(
            matched_count=len(pages),
            loader_document_count=loader_document_count,
            missing_originals=missing_originals,
            invalid_pages=invalid_pages,
            admin_section_leakage=admin_section_leakage,
            pages=pages,
        )

    def _original_page_index(self) -> "_OriginalPageIndex":
        by_filename: Dict[str, Path] = {}
        by_page_id: Dict[str, Path] = {}
        if not self.original_pages_dir.exists():
            return _OriginalPageIndex(
                by_filename=by_filename,
                by_page_id=by_page_id,
            )

        for path in sorted(self.original_pages_dir.rglob("*.md")):
            by_filename[path.name] = path
            parsed = _read_markdown_text(path.read_text(encoding="utf-8"), path=path)
            if parsed is None:
                continue
            page_id = str(parsed.frontmatter.get("id") or "").strip()
            if page_id:
                by_page_id[page_id] = path
        return _OriginalPageIndex(by_filename=by_filename, by_page_id=by_page_id)

    def _validate_loader_output(
        self,
        *,
        pages: List[ReviewedLLMWikiPageImportResult],
        output_root: Path,
        use_applied_output: bool,
    ) -> tuple[int, List[str]]:
        if use_applied_output:
            documents = self.loader.load_documents(output_root)
        else:
            with tempfile.TemporaryDirectory(prefix="llm-wiki-review-import-") as tmp:
                validation_root = Path(tmp)
                for page in pages:
                    (validation_root / page.filename).write_text(
                        page.normalized_markdown,
                        encoding="utf-8",
                    )
                documents = self.loader.load_documents(validation_root)

        leakage: List[str] = []
        for document in documents:
            content = document.page_content
            leaked_sections = [
                section for section in ADMIN_SECTION_NAMES if section in content
            ]
            if leaked_sections:
                leakage.append(
                    f"{document.metadata.get('id')}: {', '.join(leaked_sections)}"
                )
        return len(documents), leakage


@dataclass(frozen=True)
class _OriginalPageIndex:
    by_filename: Dict[str, Path]
    by_page_id: Dict[str, Path]


def _build_page_result(
    *,
    original_path: Path,
    original_text: str,
    original_frontmatter: Dict[str, Any],
    original_body: str,
    reviewed_file: Path,
    reviewed_text: str,
    reviewed_frontmatter: Dict[str, Any],
    reviewed_body: str,
    reviewer: str,
    reviewed_at: str,
) -> ReviewedLLMWikiPageImportResult:
    page_id = str(
        reviewed_frontmatter.get("id") or original_frontmatter.get("id") or ""
    ).strip()
    if not page_id:
        raise ValueError(f"Reviewed page is missing id: {reviewed_file}")

    source_refs = _durable_source_refs(
        _string_list(reviewed_frontmatter.get("source_refs"))
        or _string_list(original_frontmatter.get("source_refs"))
    )
    frontmatter = {
        **original_frontmatter,
        **reviewed_frontmatter,
        "id": page_id,
        "title": str(
            reviewed_frontmatter.get("title")
            or original_frontmatter.get("title")
            or page_id
        ).strip(),
        "type": LLM_WIKI_TYPE,
        "page_type": str(
            reviewed_frontmatter.get("page_type")
            or original_frontmatter.get("page_type")
            or "support_playbook"
        ).strip(),
        "status": REVIEWED_STATUS,
        "protocol": str(
            reviewed_frontmatter.get("protocol")
            or original_frontmatter.get("protocol")
            or "all"
        ).strip(),
        "reviewed_by": reviewer,
        "reviewed_at": reviewed_at,
        "risk_level": str(
            reviewed_frontmatter.get("risk_level")
            or original_frontmatter.get("risk_level")
            or "medium"
        ).strip(),
        "source_refs": source_refs,
    }
    normalized_markdown = _compose_markdown(frontmatter, reviewed_body)
    section_diff_summary = _section_diff_summary(
        original_text,
        normalized_markdown,
    )
    changed_sections = [
        item["section"]
        for item in section_diff_summary
        if str(item.get("section") or "") in SECTION_ORDER
    ]
    source_sensitive_additions = _source_sensitive_additions(
        original_body,
        reviewed_body,
    )
    issues = _issues(
        reviewed_text=reviewed_text,
        reviewed_frontmatter=reviewed_frontmatter,
        changed_sections=changed_sections,
        source_sensitive_additions=source_sensitive_additions,
        source_refs=source_refs,
    )
    feedback_tags = _feedback_tags_for_import(
        changed_sections=changed_sections,
        issues=issues,
    )
    title = frontmatter["title"]
    future_note = _future_generator_note(
        title=title,
        changed_sections=changed_sections,
        issues=issues,
    )

    return ReviewedLLMWikiPageImportResult(
        page_id=page_id,
        title=title,
        filename=reviewed_file.name,
        original_path=str(original_path),
        reviewed_path=str(reviewed_file),
        protocol=frontmatter["protocol"],
        source_refs=source_refs,
        normalized_markdown=normalized_markdown,
        changed_sections=changed_sections,
        section_diff_summary=section_diff_summary,
        feedback_tags=feedback_tags,
        future_generator_note=future_note,
        issues=issues,
        source_sensitive_additions=source_sensitive_additions,
        review_notes=_section_text_from_markdown(normalized_markdown, "Review Notes"),
        last_change_summary=_section_text_from_markdown(
            normalized_markdown,
            "Last Change Summary",
        ),
    )


def _feedback_tags_for_import(
    *,
    changed_sections: Iterable[str],
    issues: Iterable[str],
) -> List[str]:
    section_set = set(changed_sections)
    issue_set = set(issues)
    tags: List[str] = []
    if "Canonical Support Answer" in section_set:
        tags.append("factual_correction")
    if "Applies When" in section_set:
        tags.append("scope_narrowing")
    if "Do Not Say" in section_set:
        tags.append("missing_caveat")
    if "Evidence / Sources" in section_set or "source_coverage_needed" in issue_set:
        tags.append("source_support")
    if "copy_edit_needed" in issue_set:
        tags.append("tone_wording")
    if not tags:
        tags.append("good_generation")
    return _dedupe(tags)


def _issues(
    *,
    reviewed_text: str,
    reviewed_frontmatter: Dict[str, Any],
    changed_sections: Iterable[str],
    source_sensitive_additions: List[str],
    source_refs: List[str],
) -> List[str]:
    changed = set(changed_sections)
    issues: List[str] = []
    if (
        str(reviewed_frontmatter.get("status") or "").strip() != REVIEWED_STATUS
        or not str(reviewed_frontmatter.get("reviewed_by") or "").strip()
        or not str(reviewed_frontmatter.get("reviewed_at") or "").strip()
    ):
        issues.append("metadata_not_reviewed")
    if _has_copy_edit_signal(reviewed_text):
        issues.append("copy_edit_needed")
    if source_sensitive_additions and "Evidence / Sources" not in changed:
        issues.append("source_coverage_needed")
    if not source_refs:
        issues.append("missing_source_refs")
    return issues


def _future_generator_note(
    *,
    title: str,
    changed_sections: Iterable[str],
    issues: Iterable[str],
) -> Optional[str]:
    changed = [
        section for section in changed_sections if section not in ADMIN_SECTION_NAMES
    ]
    if not changed and "copy_edit_needed" not in set(issues):
        return None
    section_text = ", ".join(changed or ["copy/edit wording"])
    source_clause = (
        " Add durable sources when introducing numeric, path, or procedure-specific claims."
        if "source_coverage_needed" in set(issues)
        else ""
    )
    return (
        f"Human reviewer changed {section_text} for `{title}`; future drafts should "
        "preserve the reviewed support flow and avoid reintroducing removed wording."
        f"{source_clause}"
    )


def _source_sensitive_additions(before_body: str, after_body: str) -> List[str]:
    additions: List[str] = []
    before_lines = before_body.splitlines()
    after_lines = after_body.splitlines()
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines)
    for (
        tag,
        _before_start,
        _before_end,
        after_start,
        after_end,
    ) in matcher.get_opcodes():
        if tag not in {"insert", "replace"}:
            continue
        for line in after_lines[after_start:after_end]:
            cleaned = line.strip()
            if cleaned and SOURCE_SENSITIVE_RE.search(cleaned):
                additions.append(cleaned)
    return _dedupe(additions)


def _has_copy_edit_signal(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(
        re.search(rf"\b{re.escape(signal)}\b", normalized)
        for signal in COPY_EDIT_SIGNALS
    )


def _dedupe(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


@contextmanager
def _reviewed_markdown_dir(path: Path) -> Iterator[Path]:
    if path.is_dir():
        yield path
        return
    if path.suffix.lower() != ".zip":
        raise ValueError("reviewed_path must be a markdown directory or .zip file")

    with tempfile.TemporaryDirectory(prefix="reviewed-llm-wiki-") as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if member.is_dir() or not member.filename.lower().endswith(".md"):
                    continue
                filename = Path(member.filename).name
                if not filename:
                    continue
                target = root / filename
                with archive.open(member) as source:
                    target.write_bytes(source.read())
        yield root


def batch_result_to_json(result: ReviewedLLMWikiBatchImportResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True)

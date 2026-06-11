"""LLM Wiki knowledge update proposal workflow.

This service turns existing unified training candidates into reviewable,
section-level LLM Wiki changes. It deliberately keeps proposal generation
conservative: support conversations are evidence, not authority, until a human
admin approves the resulting markdown change.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml  # type: ignore[import-untyped]
from app.core.config import Settings
from app.services.rag.llm_wiki_loader import (
    INDEXABLE_STATUSES,
    LLM_WIKI_TYPE,
    REVIEWED_STATUS,
)
from app.services.training.unified_repository import UnifiedFAQCandidate

SECTION_ORDER = [
    "Canonical Support Answer",
    "Applies When",
    "Do Not Say",
    "Evidence / Sources",
    "Review Notes",
    "Last Change Summary",
]

SUPPORTED_ACTIONS = {"append_paragraph", "append_bullet", "replace_section"}
SUPPORTED_SECTIONS = set(SECTION_ORDER)


@dataclass(frozen=True)
class LLMWikiPageRecord:
    page_id: str
    title: str
    path: Path
    protocol: str
    status: str
    source_refs: List[str]
    frontmatter: Dict[str, Any]
    body: str


@dataclass(frozen=True)
class KnowledgeUpdateProposal:
    id: int
    candidate_id: int
    target_page_id: Optional[str]
    target_page_path: Optional[str]
    target_page_title: Optional[str]
    proposal_kind: str
    operations: List[Dict[str, Any]]
    preview_markdown: str
    document_markdown_override: Optional[str]
    source_refs: List[str]
    checks: List[Dict[str, Any]]
    status: str
    reviewed_by: Optional[str]
    reviewed_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: Optional[str]


class KnowledgeUpdateService:
    """Create, validate, and approve LLM Wiki knowledge update proposals."""

    def __init__(self, *, settings: Settings, db_path: str):
        self.settings = settings
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    def _init_database(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_update_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER UNIQUE NOT NULL,
                target_page_id TEXT,
                target_page_path TEXT,
                target_page_title TEXT,
                proposal_kind TEXT NOT NULL CHECK (proposal_kind IN ('update_existing', 'create_new')),
                operations_json TEXT NOT NULL,
                preview_markdown TEXT NOT NULL,
                document_markdown_override TEXT,
                source_refs_json TEXT NOT NULL,
                checks_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected', 'skipped')),
                reviewed_by TEXT,
                reviewed_at TEXT,
                rejection_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                FOREIGN KEY (candidate_id) REFERENCES unified_faq_candidates(id)
            )
            """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_kup_candidate ON knowledge_update_proposals(candidate_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_kup_status ON knowledge_update_proposals(status)"
        )
        cursor.execute("PRAGMA table_info(knowledge_update_proposals)")
        columns = {str(row[1]) for row in cursor.fetchall()}
        if "document_markdown_override" not in columns:
            cursor.execute(
                "ALTER TABLE knowledge_update_proposals ADD COLUMN document_markdown_override TEXT"
            )
        conn.commit()
        conn.close()

    def get_or_create_proposal(
        self,
        *,
        candidate: UnifiedFAQCandidate,
        force: bool = False,
    ) -> KnowledgeUpdateProposal:
        existing = self.get_by_candidate_id(candidate.id)
        if existing is not None and not force:
            return existing

        pages = self._load_pages()
        target = self._match_target_page(candidate, pages)
        proposal_kind = "update_existing" if target else "create_new"
        source_refs = self._build_source_refs(candidate)
        operations = self._build_operations(candidate, target, source_refs)
        preview = self._render_preview(
            candidate=candidate,
            target=target,
            operations=operations,
            source_refs=source_refs,
        )
        checks = self._build_checks(
            candidate=candidate,
            target=target,
            operations=operations,
            source_refs=source_refs,
            proposal_kind=proposal_kind,
            preview_markdown=preview,
            pages=pages,
        )
        return self._upsert_proposal(
            candidate_id=candidate.id,
            target_page_id=target.page_id if target else self._new_page_id(candidate),
            target_page_path=str(target.path) if target else None,
            target_page_title=(
                target.title if target else self._new_page_title(candidate)
            ),
            proposal_kind=proposal_kind,
            operations=operations,
            preview_markdown=preview,
            source_refs=source_refs,
            checks=checks,
        )

    def get_by_candidate_id(
        self, candidate_id: int
    ) -> Optional[KnowledgeUpdateProposal]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM knowledge_update_proposals WHERE candidate_id = ?",
            (candidate_id,),
        )
        row = cursor.fetchone()
        conn.close()
        return self._row_to_proposal(row) if row else None

    def update_operations(
        self,
        *,
        candidate: UnifiedFAQCandidate,
        operations: List[Dict[str, Any]],
    ) -> KnowledgeUpdateProposal:
        proposal = self.get_or_create_proposal(candidate=candidate)
        target = self._load_page_by_id(proposal.target_page_id)
        source_refs = proposal.source_refs
        preview = self._render_preview(
            candidate=candidate,
            target=target,
            operations=operations,
            source_refs=source_refs,
        )
        checks = self._build_checks(
            candidate=candidate,
            target=target,
            operations=operations,
            source_refs=source_refs,
            proposal_kind=proposal.proposal_kind,
            preview_markdown=preview,
            pages=self._load_pages(),
        )

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = _now_iso()
        cursor.execute(
            """
            UPDATE knowledge_update_proposals
            SET operations_json = ?,
                preview_markdown = ?,
                document_markdown_override = NULL,
                checks_json = ?,
                updated_at = ?
            WHERE candidate_id = ?
            """,
            (
                json.dumps(operations),
                preview,
                json.dumps(checks),
                now,
                candidate.id,
            ),
        )
        conn.commit()
        conn.close()
        return self.get_by_candidate_id(candidate.id) or proposal

    def update_document_markdown(
        self,
        *,
        candidate: UnifiedFAQCandidate,
        markdown: str,
    ) -> KnowledgeUpdateProposal:
        proposal = self.get_or_create_proposal(candidate=candidate)
        target = self._load_page_by_id(proposal.target_page_id)
        page_id = proposal.target_page_id or self._new_page_id(candidate)
        preview = self._normalize_document_markdown(
            markdown=markdown,
            candidate=candidate,
            source_refs=proposal.source_refs,
            page_id=page_id,
        )
        checks = self._build_checks(
            candidate=candidate,
            target=target,
            operations=proposal.operations,
            source_refs=proposal.source_refs,
            proposal_kind=proposal.proposal_kind,
            preview_markdown=preview,
            pages=self._load_pages(),
        )

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = _now_iso()
        cursor.execute(
            """
            UPDATE knowledge_update_proposals
            SET preview_markdown = ?,
                document_markdown_override = ?,
                checks_json = ?,
                updated_at = ?
            WHERE candidate_id = ?
            """,
            (
                preview,
                preview,
                json.dumps(checks),
                now,
                candidate.id,
            ),
        )
        conn.commit()
        conn.close()
        return self.get_by_candidate_id(candidate.id) or proposal

    def approve(
        self,
        *,
        candidate: UnifiedFAQCandidate,
        reviewer: str,
    ) -> KnowledgeUpdateProposal:
        proposal = self.get_or_create_proposal(candidate=candidate)
        blocking_failures = [
            check
            for check in proposal.checks
            if check.get("blocking") and check.get("status") == "fail"
        ]
        if blocking_failures:
            labels = ", ".join(str(check.get("label")) for check in blocking_failures)
            raise ValueError(f"Cannot approve knowledge update: {labels}")

        page_id = proposal.target_page_id or self._new_page_id(candidate)
        target = self._load_page_by_id(page_id)
        final_markdown = self._proposal_markdown(
            candidate=candidate,
            proposal=proposal,
            target=target,
            reviewer=reviewer,
        )
        output_path = (
            target.path
            if target
            else Path(self.settings.LLM_WIKI_DIR_PATH) / f"{page_id}.md"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(final_markdown, encoding="utf-8")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = _now_iso()
        cursor.execute(
            """
            UPDATE knowledge_update_proposals
            SET status = 'approved',
                reviewed_by = ?,
                reviewed_at = ?,
                updated_at = ?
            WHERE candidate_id = ?
            """,
            (reviewer, now, now, candidate.id),
        )
        conn.commit()
        conn.close()

        updated = self.get_by_candidate_id(candidate.id)
        if updated is None:
            raise ValueError("Approved proposal could not be reloaded")
        return updated

    def mark_rejected(
        self,
        *,
        candidate_id: int,
        reviewer: str,
        reason: str,
    ) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = _now_iso()
        cursor.execute(
            """
            UPDATE knowledge_update_proposals
            SET status = 'rejected',
                reviewed_by = ?,
                reviewed_at = ?,
                rejection_reason = ?,
                updated_at = ?
            WHERE candidate_id = ?
            """,
            (reviewer, now, reason, now, candidate_id),
        )
        conn.commit()
        conn.close()

    def to_response(
        self,
        proposal: KnowledgeUpdateProposal,
        candidate: UnifiedFAQCandidate,
    ) -> Dict[str, Any]:
        target = self._load_page_by_id(proposal.target_page_id)
        preview_markdown = self._proposal_markdown(
            candidate=candidate,
            proposal=proposal,
            target=target,
        )
        return {
            "id": proposal.id,
            "candidate_id": proposal.candidate_id,
            "target_page_id": proposal.target_page_id,
            "target_page_path": proposal.target_page_path,
            "target_page_title": proposal.target_page_title,
            "target_page_status": target.status if target else None,
            "proposal_kind": proposal.proposal_kind,
            "operations": proposal.operations,
            "preview_markdown": preview_markdown,
            "document_markdown_override": proposal.document_markdown_override,
            "source_refs": proposal.source_refs,
            "checks": proposal.checks,
            "status": proposal.status,
            "reviewed_by": proposal.reviewed_by,
            "reviewed_at": proposal.reviewed_at,
            "rejection_reason": proposal.rejection_reason,
            "created_at": proposal.created_at,
            "updated_at": proposal.updated_at,
            "current_page_markdown": (
                _compose_markdown(target.frontmatter, target.body) if target else None
            ),
            "candidate_question": candidate.edited_question_text
            or candidate.question_text,
            "candidate_answer": candidate.edited_staff_answer or candidate.staff_answer,
        }

    def _upsert_proposal(
        self,
        *,
        candidate_id: int,
        target_page_id: Optional[str],
        target_page_path: Optional[str],
        target_page_title: Optional[str],
        proposal_kind: str,
        operations: List[Dict[str, Any]],
        preview_markdown: str,
        source_refs: List[str],
        checks: List[Dict[str, Any]],
    ) -> KnowledgeUpdateProposal:
        source_refs = _durable_source_refs(source_refs)
        operations = _sanitize_operations(operations)
        now = _now_iso()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO knowledge_update_proposals (
                candidate_id,
                target_page_id,
                target_page_path,
                target_page_title,
                proposal_kind,
                operations_json,
                preview_markdown,
                document_markdown_override,
                source_refs_json,
                checks_json,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 'pending', ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                target_page_id = excluded.target_page_id,
                target_page_path = excluded.target_page_path,
                target_page_title = excluded.target_page_title,
                proposal_kind = excluded.proposal_kind,
                operations_json = excluded.operations_json,
                preview_markdown = excluded.preview_markdown,
                document_markdown_override = NULL,
                source_refs_json = excluded.source_refs_json,
                checks_json = excluded.checks_json,
                status = 'pending',
                reviewed_by = NULL,
                reviewed_at = NULL,
                rejection_reason = NULL,
                updated_at = excluded.updated_at
            """,
            (
                candidate_id,
                target_page_id,
                target_page_path,
                target_page_title,
                proposal_kind,
                json.dumps(operations),
                preview_markdown,
                json.dumps(source_refs),
                json.dumps(checks),
                now,
                now,
            ),
        )
        conn.commit()
        conn.close()
        proposal = self.get_by_candidate_id(candidate_id)
        if proposal is None:
            raise ValueError("Knowledge update proposal could not be persisted")
        return proposal

    def _row_to_proposal(self, row: sqlite3.Row) -> KnowledgeUpdateProposal:
        source_refs = _durable_source_refs(json.loads(row["source_refs_json"]))
        return KnowledgeUpdateProposal(
            id=row["id"],
            candidate_id=row["candidate_id"],
            target_page_id=row["target_page_id"],
            target_page_path=row["target_page_path"],
            target_page_title=row["target_page_title"],
            proposal_kind=row["proposal_kind"],
            operations=_sanitize_operations(json.loads(row["operations_json"])),
            preview_markdown=row["preview_markdown"],
            document_markdown_override=row["document_markdown_override"],
            source_refs=source_refs,
            checks=json.loads(row["checks_json"]),
            status=row["status"],
            reviewed_by=row["reviewed_by"],
            reviewed_at=row["reviewed_at"],
            rejection_reason=row["rejection_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _load_pages(self) -> List[LLMWikiPageRecord]:
        root = Path(self.settings.LLM_WIKI_DIR_PATH)
        if not root.exists():
            return []
        pages = []
        for path in sorted(root.rglob("*.md")):
            page = _read_llm_wiki_page(path)
            if page is None:
                continue
            pages.append(page)
        return pages

    def _load_page_by_id(self, page_id: Optional[str]) -> Optional[LLMWikiPageRecord]:
        if not page_id:
            return None
        return next(
            (page for page in self._load_pages() if page.page_id == page_id), None
        )

    def _match_target_page(
        self,
        candidate: UnifiedFAQCandidate,
        pages: List[LLMWikiPageRecord],
    ) -> Optional[LLMWikiPageRecord]:
        if not pages:
            return None

        source_titles = self._generated_source_titles(candidate, source_type="llm_wiki")
        for page in pages:
            if page.title in source_titles or page.page_id in source_titles:
                return page

        query = " ".join(
            filter(
                None,
                [
                    candidate.edited_question_text or candidate.question_text,
                    candidate.edited_staff_answer or candidate.staff_answer,
                    candidate.category,
                    candidate.protocol,
                ],
            )
        )
        query_tokens = _tokenize(query)
        if not query_tokens:
            return None

        best_page: Optional[LLMWikiPageRecord] = None
        best_score = 0.0
        for page in pages:
            if candidate.protocol and page.protocol not in {candidate.protocol, "all"}:
                continue
            page_tokens = _tokenize(f"{page.page_id} {page.title} {page.body[:1200]}")
            if not page_tokens:
                continue
            score = len(query_tokens & page_tokens) / max(len(query_tokens), 1)
            if score > best_score:
                best_score = score
                best_page = page

        return best_page if best_score >= 0.08 else None

    def _build_source_refs(self, candidate: UnifiedFAQCandidate) -> List[str]:
        refs: List[str] = []
        for source in _parse_sources(candidate.generated_answer_sources):
            source_type = str(
                source.get("type") or source.get("category") or ""
            ).lower()
            title = str(source.get("title") or "").strip()
            if not title:
                continue
            if source_type == "wiki":
                refs.append(f"wiki:{title}")
            elif source_type == "faq":
                refs.append(f"faq:{_faq_ref_value(source, title)}")
            elif source_type == "llm_wiki":
                refs.append(f"llm_wiki:{title}")

        return _dedupe(refs)

    def _build_operations(
        self,
        candidate: UnifiedFAQCandidate,
        target: Optional[LLMWikiPageRecord],
        source_refs: List[str],
    ) -> List[Dict[str, Any]]:
        question = _clean_inline(
            candidate.edited_question_text or candidate.question_text
        )
        answer = _clean_block(candidate.edited_staff_answer or candidate.staff_answer)
        source_name = "Matrix" if candidate.source == "matrix" else "Bisq 2"
        operations: List[Dict[str, Any]] = [
            {
                "id": "canonical-answer",
                "section": "Canonical Support Answer",
                "action": "append_paragraph",
                "content": answer,
            },
            {
                "id": "applies-when",
                "section": "Applies When",
                "action": "append_bullet",
                "content": question,
            },
            {
                "id": "review-note",
                "section": "Review Notes",
                "action": "append_bullet",
                "content": (
                    f"Derived from reviewed {source_name} support discussion "
                    f"`{candidate.source_event_id}`; verify wording before promotion to active."
                ),
            },
            {
                "id": "last-change",
                "section": "Last Change Summary",
                "action": "replace_section",
                "content": (
                    "Reviewed support discussion proposed this update through the "
                    "Knowledge Updates admin workflow."
                ),
            },
        ]

        if target is None:
            operations.insert(
                2,
                {
                    "id": "do-not-say",
                    "section": "Do Not Say",
                    "action": "append_bullet",
                    "content": "Do not extrapolate beyond the reviewed support evidence.",
                },
            )

        if source_refs:
            operations.append(
                {
                    "id": "evidence-sources",
                    "section": "Evidence / Sources",
                    "action": "append_bullet",
                    "content": ", ".join(source_refs),
                }
            )
        return operations

    def _render_preview(
        self,
        *,
        candidate: UnifiedFAQCandidate,
        target: Optional[LLMWikiPageRecord],
        operations: List[Dict[str, Any]],
        source_refs: List[str],
        reviewer: Optional[str] = None,
    ) -> str:
        source_refs = _durable_source_refs(source_refs)
        operations = _sanitize_operations(operations)
        if target:
            frontmatter = dict(target.frontmatter)
            body = target.body
        else:
            frontmatter = self._new_page_frontmatter(candidate, source_refs, reviewer)
            body = _empty_playbook_body()

        merged_refs = _durable_source_refs(
            _string_list(frontmatter.get("source_refs")) + source_refs
        )
        frontmatter.update(
            {
                "type": LLM_WIKI_TYPE,
                "page_type": frontmatter.get("page_type") or "support_playbook",
                "status": REVIEWED_STATUS,
                "protocol": frontmatter.get("protocol") or candidate.protocol or "all",
                "source_refs": merged_refs,
                "reviewed_by": reviewer
                or frontmatter.get("reviewed_by")
                or "support-admin",
                "reviewed_at": datetime.now(timezone.utc).date().isoformat(),
                "risk_level": frontmatter.get("risk_level") or _risk_level(candidate),
            }
        )
        body = _apply_operations(body, operations)
        return _compose_markdown(frontmatter, body)

    def _proposal_markdown(
        self,
        *,
        candidate: UnifiedFAQCandidate,
        proposal: KnowledgeUpdateProposal,
        target: Optional[LLMWikiPageRecord],
        reviewer: Optional[str] = None,
    ) -> str:
        page_id = proposal.target_page_id or self._new_page_id(candidate)
        if proposal.document_markdown_override:
            return self._normalize_document_markdown(
                markdown=proposal.document_markdown_override,
                candidate=candidate,
                source_refs=proposal.source_refs,
                page_id=page_id,
                reviewer=reviewer,
            )

        return self._render_preview(
            candidate=candidate,
            target=target,
            operations=proposal.operations,
            source_refs=proposal.source_refs,
            reviewer=reviewer,
        )

    def _normalize_document_markdown(
        self,
        *,
        markdown: str,
        candidate: UnifiedFAQCandidate,
        source_refs: List[str],
        page_id: str,
        reviewer: Optional[str] = None,
    ) -> str:
        parsed = _read_markdown_text(markdown)
        if parsed is None:
            raise ValueError("Document markdown must include valid YAML frontmatter")

        frontmatter = dict(parsed.frontmatter)
        merged_refs = _durable_source_refs(
            _string_list(frontmatter.get("source_refs")) + source_refs
        )
        frontmatter.update(
            {
                "id": page_id,
                "title": frontmatter.get("title") or self._new_page_title(candidate),
                "type": LLM_WIKI_TYPE,
                "page_type": frontmatter.get("page_type") or "support_playbook",
                "status": REVIEWED_STATUS,
                "protocol": frontmatter.get("protocol") or candidate.protocol or "all",
                "source_refs": merged_refs,
                "reviewed_by": reviewer
                or frontmatter.get("reviewed_by")
                or "support-admin",
                "reviewed_at": datetime.now(timezone.utc).date().isoformat(),
                "risk_level": frontmatter.get("risk_level") or _risk_level(candidate),
            }
        )
        return _compose_markdown(frontmatter, parsed.body)

    def _build_checks(
        self,
        *,
        candidate: UnifiedFAQCandidate,
        target: Optional[LLMWikiPageRecord],
        operations: List[Dict[str, Any]],
        source_refs: List[str],
        proposal_kind: str,
        preview_markdown: str,
        pages: List[LLMWikiPageRecord],
    ) -> List[Dict[str, Any]]:
        source_refs = _durable_source_refs(source_refs)
        checks: List[Dict[str, Any]] = []
        invalid_ops = [
            op
            for op in operations
            if op.get("section") not in SUPPORTED_SECTIONS
            or op.get("action") not in SUPPORTED_ACTIONS
            or not str(op.get("content") or "").strip()
        ]
        checks.append(
            _check(
                code="schema",
                label="Structured diff schema",
                status="fail" if invalid_ops else "pass",
                detail=(
                    f"{len(invalid_ops)} invalid operation(s)"
                    if invalid_ops
                    else "All proposed section operations are valid."
                ),
                blocking=True,
            )
        )
        checks.append(
            _check(
                code="source_refs",
                label="Source references",
                status="pass" if source_refs else "fail",
                detail=(
                    f"{len(source_refs)} source reference(s) attached."
                    if source_refs
                    else "Reviewed LLM Wiki pages require source references."
                ),
                blocking=True,
            )
        )

        if proposal_kind == "update_existing":
            checks.append(
                _check(
                    code="target_page",
                    label="Target page",
                    status="pass" if target else "fail",
                    detail=(
                        f"Updating `{target.page_id}`."
                        if target
                        else "Target LLM Wiki page no longer exists."
                    ),
                    blocking=True,
                )
            )
        else:
            new_id = self._new_page_id(candidate)
            duplicate = any(page.page_id == new_id for page in pages)
            checks.append(
                _check(
                    code="duplicate_page_id",
                    label="New page id",
                    status="fail" if duplicate else "pass",
                    detail=(
                        f"`{new_id}` already exists."
                        if duplicate
                        else f"`{new_id}` is available."
                    ),
                    blocking=True,
                )
            )

        contradiction = candidate.contradiction_score or 0.0
        checks.append(
            _check(
                code="contradiction",
                label="Contradiction risk",
                status="warn" if contradiction >= 0.35 else "pass",
                detail=(
                    f"Candidate contradiction score is {contradiction:.2f}; review wording carefully."
                    if contradiction >= 0.35
                    else "No high contradiction signal from comparison scoring."
                ),
                blocking=False,
            )
        )

        retrieved_llm_wiki = bool(
            self._generated_source_titles(candidate, source_type="llm_wiki")
        )
        checks.append(
            _check(
                code="retrieval_smoke",
                label="Retrieval smoke",
                status=(
                    "pass"
                    if retrieved_llm_wiki or proposal_kind == "create_new"
                    else "warn"
                ),
                detail=(
                    "The originating answer already used an LLM Wiki source."
                    if retrieved_llm_wiki
                    else "This change will only affect retrieval after the next vector-store rebuild."
                ),
                blocking=False,
            )
        )

        try:
            parsed = _read_markdown_text(preview_markdown)
            preview_valid = (
                parsed is not None
                and parsed.frontmatter.get("type") == LLM_WIKI_TYPE
                and parsed.frontmatter.get("status") in INDEXABLE_STATUSES
            )
        except Exception:
            preview_valid = False
        checks.append(
            _check(
                code="preview_markdown",
                label="Markdown preview",
                status="pass" if preview_valid else "fail",
                detail=(
                    "Preview renders as an indexable LLM Wiki page."
                    if preview_valid
                    else "Preview markdown is not a valid reviewed LLM Wiki page."
                ),
                blocking=True,
            )
        )
        return checks

    def _generated_source_titles(
        self, candidate: UnifiedFAQCandidate, *, source_type: str
    ) -> set[str]:
        titles: set[str] = set()
        for source in _parse_sources(candidate.generated_answer_sources):
            raw_type = str(source.get("type") or source.get("category") or "").lower()
            if raw_type != source_type:
                continue
            title = str(source.get("title") or "").strip()
            if title:
                titles.add(title)
        return titles

    def _new_page_id(self, candidate: UnifiedFAQCandidate) -> str:
        protocol = candidate.protocol or "all"
        base = candidate.category or candidate.question_text
        return (
            _slugify(f"{protocol}-{base}")[:80].strip("-") or f"{protocol}-support-note"
        )

    def _new_page_title(self, candidate: UnifiedFAQCandidate) -> str:
        category = (candidate.category or "Support note").strip()
        protocol = candidate.protocol or "all"
        protocol_label = {
            "bisq_easy": "Bisq Easy",
            "multisig_v1": "Bisq 1",
            "musig": "MuSig",
            "all": "General",
        }.get(protocol, protocol)
        return f"{protocol_label} {category}".strip()

    def _new_page_frontmatter(
        self,
        candidate: UnifiedFAQCandidate,
        source_refs: List[str],
        reviewer: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "id": self._new_page_id(candidate),
            "title": self._new_page_title(candidate),
            "type": LLM_WIKI_TYPE,
            "page_type": "support_playbook",
            "status": REVIEWED_STATUS,
            "protocol": candidate.protocol or "all",
            "reviewed_by": reviewer or "support-admin",
            "reviewed_at": datetime.now(timezone.utc).date().isoformat(),
            "risk_level": _risk_level(candidate),
            "source_refs": source_refs,
        }


def _read_llm_wiki_page(path: Path) -> Optional[LLMWikiPageRecord]:
    parsed = _read_markdown_text(path.read_text(encoding="utf-8"), path=path)
    if parsed is None:
        return None
    frontmatter = parsed.frontmatter
    page_id = str(frontmatter.get("id") or "").strip()
    if not page_id:
        return None
    return LLMWikiPageRecord(
        page_id=page_id,
        title=str(frontmatter.get("title") or page_id),
        path=path,
        protocol=str(frontmatter.get("protocol") or "all"),
        status=str(frontmatter.get("status") or ""),
        source_refs=_durable_source_refs(_string_list(frontmatter.get("source_refs"))),
        frontmatter=frontmatter,
        body=parsed.body,
    )


@dataclass(frozen=True)
class _ParsedMarkdown:
    frontmatter: Dict[str, Any]
    body: str


def _read_markdown_text(
    text: str, path: Optional[Path] = None
) -> Optional[_ParsedMarkdown]:
    normalized = (text or "").lstrip("\ufeff")
    if not normalized.startswith("---\n"):
        return None
    try:
        _, remainder = normalized.split("---\n", 1)
        raw_frontmatter, body = remainder.split("\n---\n", 1)
        frontmatter = yaml.safe_load(raw_frontmatter) or {}
    except Exception:
        return None
    if not isinstance(frontmatter, dict):
        return None
    return _ParsedMarkdown(frontmatter=frontmatter, body=body.strip())


def _apply_operations(body: str, operations: List[Dict[str, Any]]) -> str:
    prefix, sections = _split_sections(body)
    for name in SECTION_ORDER:
        sections.setdefault(name, [])

    for operation in operations:
        section = str(operation.get("section") or "").strip()
        action = str(operation.get("action") or "").strip()
        content = _clean_block(str(operation.get("content") or ""))
        if (
            section not in SUPPORTED_SECTIONS
            or action not in SUPPORTED_ACTIONS
            or not content
        ):
            continue
        if action == "replace_section":
            sections[section] = _lines(content)
        elif action == "append_bullet":
            bullet = content if content.startswith("- ") else f"- {content}"
            _append_with_gap(sections[section], [bullet])
        elif action == "append_paragraph":
            _append_with_gap(sections[section], _lines(content))

    return _compose_body(prefix, sections)


def _split_sections(body: str) -> tuple[List[str], OrderedDict[str, List[str]]]:
    prefix: List[str] = []
    sections: OrderedDict[str, List[str]] = OrderedDict()
    current: Optional[str] = None
    for line in (body or "").splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
            continue
        if current is None:
            prefix.append(line)
        else:
            sections[current].append(line)
    return prefix, sections


def _compose_body(prefix: List[str], sections: OrderedDict[str, List[str]]) -> str:
    parts: List[str] = []
    if any(line.strip() for line in prefix):
        parts.append("\n".join(prefix).strip())
    ordered_names = [name for name in SECTION_ORDER if name in sections]
    ordered_names.extend(name for name in sections.keys() if name not in SECTION_ORDER)
    for name in ordered_names:
        content = "\n".join(sections[name]).strip()
        parts.append(f"## {name}\n\n{content}".rstrip())
    return "\n\n".join(parts).strip() + "\n"


def _compose_markdown(frontmatter: Dict[str, Any], body: str) -> str:
    frontmatter_text = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=False,
    ).strip()
    return f"---\n{frontmatter_text}\n---\n{body.strip()}\n"


def _empty_playbook_body() -> str:
    return "\n\n".join(f"## {section}\n" for section in SECTION_ORDER).strip() + "\n"


def _append_with_gap(existing: List[str], addition: List[str]) -> None:
    while existing and not existing[-1].strip():
        existing.pop()
    if existing:
        existing.append("")
    existing.extend(addition)


def _lines(value: str) -> List[str]:
    return value.strip().splitlines()


def _parse_sources(raw: Optional[str]) -> List[Dict[str, Any]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _faq_ref_value(source: Dict[str, Any], fallback: str) -> str:
    source_id = source.get("id") or source.get("faq_id")
    if source_id:
        return str(source_id).strip()
    url = str(source.get("url") or "").strip()
    if url:
        return url.rstrip("/").rsplit("/", 1)[-1] or fallback
    return fallback.strip()


def _durable_source_refs(refs: Iterable[str]) -> List[str]:
    """Keep only source refs that can be re-opened without stored chat logs."""
    return _dedupe(
        ref for ref in refs if not str(ref).strip().lower().startswith("support:")
    )


def _sanitize_operations(operations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sanitized: List[Dict[str, Any]] = []
    for operation in operations:
        if operation.get("id") != "evidence-sources":
            sanitized.append(operation)
            continue

        refs = [ref.strip() for ref in str(operation.get("content") or "").split(",")]
        durable_refs = _durable_source_refs(refs)
        if durable_refs:
            sanitized.append({**operation, "content": ", ".join(durable_refs)})
    return sanitized


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


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


def _tokenize(value: str) -> set[str]:
    stopwords = {
        "about",
        "after",
        "answer",
        "bisq",
        "from",
        "have",
        "that",
        "this",
        "user",
        "with",
        "what",
        "when",
        "where",
        "will",
        "your",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", value.lower())
        if token not in stopwords
    }


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return re.sub(r"-+", "-", slug).strip("-")


def _clean_inline(value: str) -> str:
    return " ".join(str(value or "").split())


def _clean_block(value: str) -> str:
    return "\n".join(line.rstrip() for line in str(value or "").strip().splitlines())


def _risk_level(candidate: UnifiedFAQCandidate) -> str:
    if (candidate.hallucination_risk or 0.0) >= 0.45 or (
        candidate.contradiction_score or 0.0
    ) >= 0.35:
        return "high"
    if candidate.protocol == "multisig_v1":
        return "medium"
    return "low"


def _check(
    *,
    code: str,
    label: str,
    status: str,
    detail: str,
    blocking: bool,
) -> Dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "status": status,
        "detail": detail,
        "blocking": blocking,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

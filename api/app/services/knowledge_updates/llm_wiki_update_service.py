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
from urllib.parse import quote

import yaml  # type: ignore[import-untyped]
from app.core.config import Settings
from app.services.faq.slug_manager import SlugManager
from app.services.knowledge_updates.topic_clusters import (
    KnowledgeTopicCluster,
    topic_cluster_key,
)
from app.services.rag.llm_wiki_loader import (
    ALLOWED_PROTOCOLS,
    INDEXABLE_STATUSES,
    LLM_WIKI_TYPE,
    REVIEWED_STATUS,
)
from app.services.rag.protocol_detector import ProtocolDetector
from app.services.rag.source_refs import (
    code_source_refs,
    imprecise_code_source_refs,
)
from app.services.training.unified_repository import UnifiedFAQCandidate
from app.utils.wiki_url_generator import generate_wiki_url

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
VALID_PROTOCOLS = set(ALLOWED_PROTOCOLS)
PROTOCOL_CONFLICT_CONFIDENCE = 0.85
MIN_TARGET_PAGE_TOKEN_COVERAGE = 0.22
MIN_TARGET_TITLE_TOKEN_OVERLAP = 0.15
THIN_ANSWER_MIN_CHARS = 80
THIN_ANSWER_PATTERNS = (
    "notify the counterparty",
    "contact support",
    "team member",
    "someone will follow up",
    "try again",
    "restart the app",
)
SITUATIONAL_QUESTION_TERMS = (
    "my account",
    "my trade",
    "my open trade",
    "temporarily locked",
    "locked out",
    "notify my counterparty",
    "support ticket",
    "error message",
    "screenshot",
)
SOURCE_SUPPORT_WARN_THRESHOLD = 0.20
GENERATOR_VERSION = "knowledge-update-heuristic-v2"
PROMPT_VERSION: Optional[str] = None
MAX_GENERATOR_FEEDBACK_EXAMPLES = 5
GENERATOR_FEEDBACK_EXPORT_LIMIT = 100
PROPOSAL_FEEDBACK_COLUMNS = {
    "generated_markdown": "TEXT",
    "approved_markdown": "TEXT",
    "review_notes": "TEXT",
    "last_change_summary": "TEXT",
    "feedback_tags_json": "TEXT",
    "future_generator_note": "TEXT",
    "section_diff_summary_json": "TEXT",
    "generator_version": "TEXT",
    "prompt_version": "TEXT",
    "applied_feedback_json": "TEXT",
}
SOURCE_SUPPORT_STOPWORDS = {
    "about",
    "after",
    "answer",
    "bisq",
    "bitcoin",
    "btc",
    "could",
    "does",
    "from",
    "have",
    "should",
    "that",
    "this",
    "trade",
    "trades",
    "user",
    "users",
    "what",
    "when",
    "where",
    "will",
    "with",
    "would",
    "your",
}
FEEDBACK_TAG_GUIDANCE = {
    "factual_correction": "Verify generated claims against durable sources before approval.",
    "scope_narrowing": "Keep guidance narrowly tied to the reviewed support evidence.",
    "source_support": "Prefer durable wiki, FAQ, or LLM Wiki refs before keeping a claim.",
    "protocol_version": "Keep protocol and version scope explicit when evidence is version-sensitive.",
    "tone_wording": "Use concise support wording without changing product meaning.",
    "wrong_section": "Place answer rules in answer-facing sections and audit notes in Review Notes.",
    "missing_caveat": "Add caveats as guardrails instead of broad canonical claims.",
}
FEEDBACK_TAG_LABELS = {
    "good_generation": "Good generation",
    "factual_correction": "Factual correction",
    "scope_narrowing": "Scope narrowed",
    "source_support": "Source support",
    "protocol_version": "Protocol/version",
    "tone_wording": "Tone/wording",
    "wrong_section": "Wrong section",
    "missing_caveat": "Missing caveat",
}
_PROTOCOL_DETECTOR = ProtocolDetector()


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
    generated_markdown: Optional[str]
    approved_markdown: Optional[str]
    review_notes: Optional[str]
    last_change_summary: Optional[str]
    feedback_tags: List[str]
    future_generator_note: Optional[str]
    section_diff_summary: List[Dict[str, Any]]
    generator_version: str
    prompt_version: Optional[str]
    generator_feedback: Dict[str, Any]
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
        self._pages_cache: Optional[List[LLMWikiPageRecord]] = None
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
                generated_markdown TEXT,
                approved_markdown TEXT,
                review_notes TEXT,
                last_change_summary TEXT,
                feedback_tags_json TEXT,
                future_generator_note TEXT,
                section_diff_summary_json TEXT,
                generator_version TEXT,
                prompt_version TEXT,
                applied_feedback_json TEXT,
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
        for column, column_type in PROPOSAL_FEEDBACK_COLUMNS.items():
            if column not in columns:
                cursor.execute(
                    f"ALTER TABLE knowledge_update_proposals ADD COLUMN {column} {column_type}"
                )
        cursor.execute("""
            UPDATE knowledge_update_proposals
            SET generated_markdown = preview_markdown
            WHERE generated_markdown IS NULL
            """)
        cursor.execute("""
            UPDATE knowledge_update_proposals
            SET feedback_tags_json = '[]'
            WHERE feedback_tags_json IS NULL
            """)
        cursor.execute("""
            UPDATE knowledge_update_proposals
            SET section_diff_summary_json = '[]'
            WHERE section_diff_summary_json IS NULL
            """)
        cursor.execute(
            """
            UPDATE knowledge_update_proposals
            SET generator_version = ?
            WHERE generator_version IS NULL
            """,
            (GENERATOR_VERSION,),
        )
        cursor.execute("""
            UPDATE knowledge_update_proposals
            SET applied_feedback_json = '{}'
            WHERE applied_feedback_json IS NULL
            """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS llm_wiki_review_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL DEFAULT 'batch_import',
                source_batch_id TEXT,
                target_page_id TEXT NOT NULL,
                target_page_title TEXT,
                page_path TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                review_notes TEXT,
                last_change_summary TEXT,
                feedback_tags_json TEXT NOT NULL,
                future_generator_note TEXT,
                section_diff_summary_json TEXT NOT NULL,
                generator_version TEXT,
                prompt_version TEXT,
                protocol TEXT,
                category TEXT,
                source_refs_json TEXT NOT NULL,
                original_markdown TEXT,
                reviewed_markdown TEXT,
                normalized_markdown TEXT,
                issues_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
            """)
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_wiki_review_feedback_unique
            ON llm_wiki_review_feedback (
                source,
                target_page_id,
                reviewed_by,
                reviewed_at
            )
            """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_llm_wiki_review_feedback_target
            ON llm_wiki_review_feedback (target_page_id)
            """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_llm_wiki_review_feedback_reviewer
            ON llm_wiki_review_feedback (reviewed_by)
            """)
        conn.commit()
        conn.close()

    def get_or_create_proposal(
        self,
        *,
        candidate: UnifiedFAQCandidate,
        cluster: Optional[KnowledgeTopicCluster] = None,
        force: bool = False,
    ) -> KnowledgeUpdateProposal:
        existing = self.get_by_candidate_id(candidate.id)
        if (
            existing is not None
            and not force
            and _proposal_has_cluster_context(existing, cluster)
        ):
            return existing

        pages = self._load_pages()
        target = self._match_target_page(candidate, pages)
        proposal_kind = "update_existing" if target else "create_new"
        source_refs = self._build_source_refs(candidate, cluster=cluster)
        generator_feedback = self._build_generator_feedback_context(
            candidate=candidate,
            target=target,
        )
        operations = self._build_operations(
            candidate,
            target,
            source_refs,
            cluster=cluster,
            generator_feedback=generator_feedback,
        )
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
            requires_cluster_synthesis=cluster is not None,
            document_override_present=False,
            generator_feedback=generator_feedback,
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
            generator_feedback=generator_feedback,
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

    def candidate_reviewability_issues(
        self, candidate: UnifiedFAQCandidate
    ) -> List[str]:
        """Return fundamental reasons a candidate should not enter LLM Wiki review."""
        issues: List[str] = []
        if not candidate.protocol:
            issues.append("missing_protocol")
        elif candidate.protocol not in VALID_PROTOCOLS:
            issues.append("unsupported_protocol")
        elif _candidate_protocol_conflict(candidate):
            issues.append("protocol_conflict")
        if not self._build_source_refs(candidate):
            issues.append("missing_source_refs")
        if _candidate_reusability_issues(candidate):
            issues.append("low_reusability")
        return issues

    def is_candidate_reviewable(self, candidate: UnifiedFAQCandidate) -> bool:
        return not self.candidate_reviewability_issues(candidate)

    def review_cluster_key(self, candidate: UnifiedFAQCandidate) -> str:
        """Return the conservative key used to collapse admin review items.

        Broad support topics are not enough: one approval marks every cluster
        member reviewed. The key therefore includes the inferred target page and
        category so only small, same-page edits collapse into one synthesis item.
        """
        target = self._match_target_page(candidate, self._load_pages())
        target_id = target.page_id if target else self._new_page_id(candidate)
        topic = topic_cluster_key(candidate).split("|", 1)[-1]
        category = _slugify(candidate.category or "uncategorized")
        return f"{candidate.protocol or 'none'}|{target_id}|{category}|{topic}"

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
            requires_cluster_synthesis=_operations_require_cluster_synthesis(
                operations
            ),
            document_override_present=False,
            generator_feedback=proposal.generator_feedback,
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
        source_refs = _effective_source_refs(proposal.source_refs, preview)
        checks = self._build_checks(
            candidate=candidate,
            target=target,
            operations=proposal.operations,
            source_refs=source_refs,
            proposal_kind=proposal.proposal_kind,
            preview_markdown=preview,
            pages=self._load_pages(),
            requires_cluster_synthesis=_operations_require_cluster_synthesis(
                proposal.operations
            ),
            document_override_present=True,
            generator_feedback=proposal.generator_feedback,
        )

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = _now_iso()
        cursor.execute(
            """
            UPDATE knowledge_update_proposals
            SET preview_markdown = ?,
                document_markdown_override = ?,
                source_refs_json = ?,
                checks_json = ?,
                updated_at = ?
            WHERE candidate_id = ?
            """,
            (
                preview,
                preview,
                json.dumps(source_refs),
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
        cluster: Optional[KnowledgeTopicCluster] = None,
        feedback_tags: Optional[Iterable[str]] = None,
        future_generator_note: Optional[str] = None,
    ) -> KnowledgeUpdateProposal:
        proposal = self.get_or_create_proposal(candidate=candidate, cluster=cluster)
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
        review_notes = _section_text_from_markdown(final_markdown, "Review Notes")
        last_change_summary = _section_text_from_markdown(
            final_markdown,
            "Last Change Summary",
        )
        generated_markdown = proposal.generated_markdown or proposal.preview_markdown
        section_diff_summary = _section_diff_summary(
            generated_markdown,
            final_markdown,
        )
        normalized_feedback_tags = _feedback_tags(feedback_tags or [])
        normalized_generator_note = _optional_text(future_generator_note)
        output_path = (
            target.path
            if target
            else Path(self.settings.LLM_WIKI_DIR_PATH) / f"{page_id}.md"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(final_markdown, encoding="utf-8")
        self._pages_cache = None

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = _now_iso()
        cursor.execute(
            """
            UPDATE knowledge_update_proposals
            SET status = 'approved',
                reviewed_by = ?,
                reviewed_at = ?,
                approved_markdown = ?,
                review_notes = ?,
                last_change_summary = ?,
                feedback_tags_json = ?,
                future_generator_note = ?,
                section_diff_summary_json = ?,
                generator_version = ?,
                prompt_version = ?,
                updated_at = ?
            WHERE candidate_id = ?
            """,
            (
                reviewer,
                now,
                final_markdown,
                review_notes,
                last_change_summary,
                json.dumps(normalized_feedback_tags),
                normalized_generator_note,
                json.dumps(section_diff_summary),
                proposal.generator_version or GENERATOR_VERSION,
                proposal.prompt_version,
                now,
                candidate.id,
            ),
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
            "generated_markdown": proposal.generated_markdown,
            "approved_markdown": proposal.approved_markdown,
            "review_notes": proposal.review_notes,
            "last_change_summary": proposal.last_change_summary,
            "feedback_tags": proposal.feedback_tags,
            "future_generator_note": proposal.future_generator_note,
            "section_diff_summary": proposal.section_diff_summary,
            "generator_version": proposal.generator_version,
            "prompt_version": proposal.prompt_version,
            "generator_feedback": proposal.generator_feedback,
            "source_refs": proposal.source_refs,
            "source_ref_links": _source_ref_links_for_refs(
                self.settings, proposal.source_refs
            ),
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
        generator_feedback: Dict[str, Any],
    ) -> KnowledgeUpdateProposal:
        source_refs = _durable_source_refs(source_refs)
        operations = _sanitize_operations(operations)
        generator_feedback = _generator_feedback_context(generator_feedback)
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
                generated_markdown,
                approved_markdown,
                review_notes,
                last_change_summary,
                feedback_tags_json,
                future_generator_note,
                section_diff_summary_json,
                generator_version,
                prompt_version,
                applied_feedback_json,
                source_refs_json,
                checks_json,
                status,
                created_at,
                updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL, NULL, ?, NULL, ?, ?,
                ?, ?, ?, ?, 'pending', ?, ?
            )
            ON CONFLICT(candidate_id) DO UPDATE SET
                target_page_id = excluded.target_page_id,
                target_page_path = excluded.target_page_path,
                target_page_title = excluded.target_page_title,
                proposal_kind = excluded.proposal_kind,
                operations_json = excluded.operations_json,
                preview_markdown = excluded.preview_markdown,
                document_markdown_override = NULL,
                generated_markdown = excluded.generated_markdown,
                approved_markdown = NULL,
                review_notes = NULL,
                last_change_summary = NULL,
                feedback_tags_json = excluded.feedback_tags_json,
                future_generator_note = NULL,
                section_diff_summary_json = excluded.section_diff_summary_json,
                generator_version = excluded.generator_version,
                prompt_version = excluded.prompt_version,
                applied_feedback_json = excluded.applied_feedback_json,
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
                preview_markdown,
                json.dumps([]),
                json.dumps([]),
                GENERATOR_VERSION,
                PROMPT_VERSION,
                json.dumps(generator_feedback),
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
            generated_markdown=row["generated_markdown"],
            approved_markdown=row["approved_markdown"],
            review_notes=row["review_notes"],
            last_change_summary=row["last_change_summary"],
            feedback_tags=_feedback_tags_from_json(row["feedback_tags_json"]),
            future_generator_note=row["future_generator_note"],
            section_diff_summary=_section_diff_summary_from_json(
                row["section_diff_summary_json"]
            ),
            generator_version=row["generator_version"] or GENERATOR_VERSION,
            prompt_version=row["prompt_version"],
            generator_feedback=_generator_feedback_from_json(
                row["applied_feedback_json"]
            ),
            source_refs=source_refs,
            checks=json.loads(row["checks_json"]),
            status=row["status"],
            reviewed_by=row["reviewed_by"],
            reviewed_at=row["reviewed_at"],
            rejection_reason=row["rejection_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_generator_feedback_records(
        self,
        *,
        limit: int = GENERATOR_FEEDBACK_EXPORT_LIMIT,
        target_page_id: Optional[str] = None,
        reviewer: Optional[str] = None,
        protocol: Optional[str] = None,
        category: Optional[str] = None,
        exclude_candidate_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        records = [
            *self._list_proposal_generator_feedback_records(
                limit=limit,
                target_page_id=target_page_id,
                reviewer=reviewer,
                protocol=protocol,
                category=category,
                exclude_candidate_id=exclude_candidate_id,
            ),
            *self._list_external_generator_feedback_records(
                limit=limit,
                target_page_id=target_page_id,
                reviewer=reviewer,
                protocol=protocol,
                category=category,
            ),
        ]
        return sorted(
            records,
            key=lambda record: (
                str(record.get("reviewed_at") or ""),
                int(record.get("proposal_id") or record.get("feedback_id") or 0),
            ),
            reverse=True,
        )[:limit]

    def record_external_review_feedback(
        self,
        *,
        target_page_id: str,
        target_page_title: Optional[str],
        page_path: Optional[str],
        reviewed_by: Optional[str],
        reviewed_at: Optional[str],
        review_notes: Optional[str],
        last_change_summary: Optional[str],
        feedback_tags: Iterable[str],
        future_generator_note: Optional[str],
        section_diff_summary: List[Dict[str, Any]],
        protocol: Optional[str],
        category: Optional[str] = None,
        source_refs: Optional[Iterable[str]] = None,
        original_markdown: Optional[str] = None,
        reviewed_markdown: Optional[str] = None,
        normalized_markdown: Optional[str] = None,
        issues: Optional[Iterable[str]] = None,
        source: str = "batch_import",
        source_batch_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist externally reviewed LLM Wiki edits as generator feedback.

        Offline batch review does not have a training-candidate id, but the
        reviewer edits are still useful examples for future proposals targeting
        the same page or protocol/category.
        """

        page_id = _optional_text(target_page_id)
        if not page_id:
            raise ValueError("target_page_id is required")
        source_name = _optional_text(source) or "batch_import"
        reviewer_name = _optional_text(reviewed_by)
        if not reviewer_name:
            raise ValueError("reviewed_by is required")
        reviewed_at_value = _optional_text(reviewed_at) or _now_iso()
        normalized_tags = _feedback_tags(feedback_tags)
        normalized_diff = _section_diff_summary_from_json(
            json.dumps(section_diff_summary or [])
        )
        normalized_issues = _dedupe(str(issue) for issue in issues or [])
        refs = _durable_source_refs(source_refs or [])
        category_key = _category_key(category)
        now = _now_iso()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO llm_wiki_review_feedback (
                source,
                source_batch_id,
                target_page_id,
                target_page_title,
                page_path,
                reviewed_by,
                reviewed_at,
                review_notes,
                last_change_summary,
                feedback_tags_json,
                future_generator_note,
                section_diff_summary_json,
                generator_version,
                prompt_version,
                protocol,
                category,
                source_refs_json,
                original_markdown,
                reviewed_markdown,
                normalized_markdown,
                issues_json,
                created_at,
                updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(source, target_page_id, reviewed_by, reviewed_at) DO UPDATE SET
                source_batch_id = excluded.source_batch_id,
                target_page_title = excluded.target_page_title,
                page_path = excluded.page_path,
                review_notes = excluded.review_notes,
                last_change_summary = excluded.last_change_summary,
                feedback_tags_json = excluded.feedback_tags_json,
                future_generator_note = excluded.future_generator_note,
                section_diff_summary_json = excluded.section_diff_summary_json,
                generator_version = excluded.generator_version,
                prompt_version = excluded.prompt_version,
                protocol = excluded.protocol,
                category = excluded.category,
                source_refs_json = excluded.source_refs_json,
                original_markdown = excluded.original_markdown,
                reviewed_markdown = excluded.reviewed_markdown,
                normalized_markdown = excluded.normalized_markdown,
                issues_json = excluded.issues_json,
                updated_at = excluded.updated_at
            """,
            (
                source_name,
                _optional_text(source_batch_id),
                page_id,
                _optional_text(target_page_title),
                _optional_text(page_path),
                reviewer_name,
                reviewed_at_value,
                _optional_text(review_notes),
                _optional_text(last_change_summary),
                json.dumps(normalized_tags),
                _optional_text(future_generator_note),
                json.dumps(normalized_diff),
                GENERATOR_VERSION,
                PROMPT_VERSION,
                _optional_text(protocol),
                category_key,
                json.dumps(refs),
                original_markdown,
                reviewed_markdown,
                normalized_markdown,
                json.dumps(normalized_issues),
                now,
                now,
            ),
        )
        row = cursor.execute(
            """
            SELECT *
            FROM llm_wiki_review_feedback
            WHERE source = ?
              AND target_page_id = ?
              AND coalesce(reviewed_by, '') = coalesce(?, '')
              AND reviewed_at = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (source_name, page_id, reviewer_name, reviewed_at_value),
        ).fetchone()
        conn.commit()
        conn.close()
        if row is None:
            raise ValueError("External review feedback could not be persisted")
        return _external_feedback_record_from_row(row)

    def _list_proposal_generator_feedback_records(
        self,
        *,
        limit: int,
        target_page_id: Optional[str],
        reviewer: Optional[str],
        protocol: Optional[str],
        category: Optional[str],
        exclude_candidate_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.create_function("slugify", 1, lambda value: _slugify(str(value or "")))
        try:
            has_candidates = _sqlite_table_exists(conn, "unified_faq_candidates")
            filters = ["p.status = 'approved'"]
            params: List[Any] = []
            if exclude_candidate_id is not None:
                filters.append("p.candidate_id != ?")
                params.append(exclude_candidate_id)
            cleaned_reviewer = _optional_text(reviewer)
            if cleaned_reviewer:
                filters.append("lower(coalesce(p.reviewed_by, '')) = lower(?)")
                params.append(cleaned_reviewer)
            match_filters: List[str] = []
            if target_page_id:
                match_filters.append("p.target_page_id = ?")
                params.append(target_page_id)
            cleaned_protocol = _optional_text(protocol)
            cleaned_category = _optional_text(category)
            if has_candidates and cleaned_protocol and cleaned_category:
                match_filters.append(
                    "(c.protocol = ? AND slugify(coalesce(c.category, '')) = ?)"
                )
                params.extend([cleaned_protocol, _slugify(cleaned_category)])
            if match_filters:
                filters.append(f"({' OR '.join(match_filters)})")
            where_clause = " AND ".join(filters)
            if has_candidates:
                query = f"""
                    SELECT
                        p.*,
                        c.protocol AS candidate_protocol,
                        c.category AS candidate_category,
                        c.question_text AS candidate_question
                    FROM knowledge_update_proposals p
                    LEFT JOIN unified_faq_candidates c ON c.id = p.candidate_id
                    WHERE {where_clause}
                    ORDER BY p.reviewed_at DESC, p.id DESC
                    LIMIT ?
                """
            else:
                query = f"""
                    SELECT
                        p.*,
                        NULL AS candidate_protocol,
                        NULL AS candidate_category,
                        NULL AS candidate_question
                    FROM knowledge_update_proposals p
                    WHERE {where_clause}
                    ORDER BY p.reviewed_at DESC, p.id DESC
                    LIMIT ?
                """
            rows = conn.execute(query, [*params, limit]).fetchall()
            return [_feedback_record_from_row(row) for row in rows]
        finally:
            conn.close()

    def _list_external_generator_feedback_records(
        self,
        *,
        limit: int,
        target_page_id: Optional[str],
        reviewer: Optional[str],
        protocol: Optional[str],
        category: Optional[str],
    ) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            filters = ["1 = 1"]
            params: List[Any] = []
            cleaned_reviewer = _optional_text(reviewer)
            if cleaned_reviewer:
                filters.append("lower(coalesce(reviewed_by, '')) = lower(?)")
                params.append(cleaned_reviewer)
            match_filters: List[str] = []
            if target_page_id:
                match_filters.append("target_page_id = ?")
                params.append(target_page_id)
            cleaned_protocol = _optional_text(protocol)
            cleaned_category = _optional_text(category)
            if cleaned_protocol and cleaned_category:
                match_filters.append("(protocol = ? AND category = ?)")
                params.extend([cleaned_protocol, _slugify(cleaned_category)])
            if match_filters:
                filters.append(f"({' OR '.join(match_filters)})")
            where_clause = " AND ".join(filters)
            rows = conn.execute(
                f"""
                SELECT *
                FROM llm_wiki_review_feedback
                WHERE {where_clause}
                ORDER BY reviewed_at DESC, id DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
            return [_external_feedback_record_from_row(row) for row in rows]
        finally:
            conn.close()

    def _build_generator_feedback_context(
        self,
        *,
        candidate: UnifiedFAQCandidate,
        target: Optional[LLMWikiPageRecord],
    ) -> Dict[str, Any]:
        target_page_id = target.page_id if target else self._new_page_id(candidate)
        records = self.list_generator_feedback_records(
            limit=MAX_GENERATOR_FEEDBACK_EXAMPLES,
            target_page_id=target_page_id,
            protocol=candidate.protocol,
            category=candidate.category,
            exclude_candidate_id=candidate.id,
        )
        matching_records = [
            record
            for record in records
            if _feedback_record_matches_candidate(
                record,
                candidate=candidate,
                target_page_id=target_page_id,
            )
        ]

        if not matching_records:
            return _empty_generator_feedback_context()

        feedback_tags = _dedupe(
            tag
            for record in matching_records
            for tag in record.get("feedback_tags", [])
        )
        notes = _dedupe(
            note
            for record in matching_records
            for note in _feedback_record_notes(record)
        )[:MAX_GENERATOR_FEEDBACK_EXAMPLES]
        return _generator_feedback_context(
            {
                "example_count": len(matching_records),
                "feedback_tags": feedback_tags,
                "guidance": _guidance_for_feedback_tags(feedback_tags),
                "notes": notes,
                "examples": [
                    {
                        "review_source": record.get("review_source", "proposal"),
                        "proposal_id": record.get("proposal_id"),
                        "feedback_id": record.get("feedback_id"),
                        "candidate_id": record.get("candidate_id"),
                        "target_page_id": record["target_page_id"],
                        "feedback_tags": record["feedback_tags"],
                        "future_generator_note": record["future_generator_note"],
                        "last_change_summary": record["last_change_summary"],
                        "section_diff_summary": record["section_diff_summary"],
                    }
                    for record in matching_records
                ],
            }
        )

    def _load_pages(self) -> List[LLMWikiPageRecord]:
        if self._pages_cache is not None:
            return self._pages_cache
        root = Path(self.settings.LLM_WIKI_DIR_PATH)
        if not root.exists():
            self._pages_cache = []
            return []
        pages = []
        for path in sorted(root.rglob("*.md")):
            page = _read_llm_wiki_page(path)
            if page is None:
                continue
            pages.append(page)
        self._pages_cache = pages
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
        if candidate.protocol not in VALID_PROTOCOLS:
            return None

        source_titles = self._generated_source_titles(candidate, source_type="llm_wiki")
        for page in pages:
            if page.status == "deprecated":
                continue
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
            if page.status == "deprecated":
                continue
            if page.protocol not in {candidate.protocol, "all"}:
                continue
            page_tokens = _tokenize(f"{page.page_id} {page.title} {page.body[:1200]}")
            title_tokens = _tokenize(f"{page.page_id} {page.title}")
            if not page_tokens:
                continue
            score = len(query_tokens & page_tokens) / max(len(query_tokens), 1)
            title_overlap = len(query_tokens & title_tokens) / max(len(title_tokens), 1)
            if (
                score >= MIN_TARGET_PAGE_TOKEN_COVERAGE
                and title_overlap >= MIN_TARGET_TITLE_TOKEN_OVERLAP
                and score > best_score
            ):
                best_score = score
                best_page = page

        return best_page

    def _build_source_refs(
        self,
        candidate: UnifiedFAQCandidate,
        *,
        cluster: Optional[KnowledgeTopicCluster] = None,
    ) -> List[str]:
        refs: List[str] = []
        candidates = cluster.candidates if cluster else [candidate]
        for source_candidate in candidates:
            for source in _parse_sources(source_candidate.generated_answer_sources):
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
                elif source_type in {"code", "code_fact"}:
                    source_ref = str(source.get("source_ref") or "").strip()
                    if source_ref:
                        refs.append(source_ref)

        return _dedupe(refs)

    def _build_operations(
        self,
        candidate: UnifiedFAQCandidate,
        target: Optional[LLMWikiPageRecord],
        source_refs: List[str],
        *,
        cluster: Optional[KnowledgeTopicCluster] = None,
        generator_feedback: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        question = _clean_inline(
            candidate.edited_question_text or candidate.question_text
        )
        answer = _clean_block(candidate.edited_staff_answer or candidate.staff_answer)
        applies_when = question
        last_change_summary = "Updated through the Knowledge Updates admin workflow."
        if cluster is not None:
            answer = _cluster_canonical_answer(cluster)
            applies_when = _cluster_applies_when(cluster)
            last_change_summary = _cluster_last_change_summary(cluster)
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
                "content": applies_when,
            },
            {
                "id": "last-change",
                "section": "Last Change Summary",
                "action": "replace_section",
                "content": last_change_summary,
            },
        ]

        if cluster is not None:
            operations.append(
                {
                    "id": "cluster-synthesis",
                    "section": "Review Notes",
                    "action": "append_bullet",
                    "content": _cluster_synthesis_note(cluster),
                }
            )

        feedback_note = _generator_feedback_note(generator_feedback)
        if feedback_note:
            operations.append(
                {
                    "id": "generator-feedback",
                    "section": "Review Notes",
                    "action": "append_bullet",
                    "content": feedback_note,
                }
            )

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
                    "content": "\n".join(f"`{ref}`" for ref in source_refs),
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
        requires_cluster_synthesis: bool = False,
        document_override_present: bool = False,
        generator_feedback: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        source_refs = _effective_source_refs(source_refs, preview_markdown)
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
        code_refs = code_source_refs(source_refs)
        invalid_code_refs = imprecise_code_source_refs(source_refs)
        if code_refs:
            checks.append(
                _check(
                    code="code_source_refs",
                    label="Code source references",
                    status="fail" if invalid_code_refs else "pass",
                    detail=(
                        "Code-derived claims must cite pinned commit refs with line ranges."
                        if invalid_code_refs
                        else f"{len(code_refs)} precise code source reference(s) attached."
                    ),
                    blocking=True,
                )
            )
        protocol = candidate.protocol
        checks.append(
            _check(
                code="candidate_protocol",
                label="Candidate protocol",
                status="pass" if protocol in VALID_PROTOCOLS else "fail",
                detail=(
                    f"Candidate is tagged `{protocol}`."
                    if protocol in VALID_PROTOCOLS
                    else (
                        f"Candidate protocol `{protocol}` is not indexable by the LLM Wiki loader."
                        if protocol
                        else "Candidate must have an explicit Bisq protocol before promotion."
                    )
                ),
                blocking=True,
            )
        )
        protocol_conflict = _candidate_protocol_conflict(candidate)
        checks.append(
            _check(
                code="candidate_protocol_consistency",
                label="Protocol consistency",
                status="fail" if protocol_conflict else "pass",
                detail=(
                    "Question text strongly indicates "
                    f"`{protocol_conflict[0]}` "
                    f"(confidence {protocol_conflict[1]:.2f}) but the candidate "
                    f"is tagged `{protocol}`. Regenerate or reclassify before "
                    "promotion."
                    if protocol_conflict
                    else "No strong conflicting protocol signal found in the user question."
                ),
                blocking=True,
            )
        )

        reusability_issues = _candidate_reusability_issues(candidate)
        checks.append(
            _check(
                code="candidate_reusability",
                label="Candidate reusability",
                status="fail" if reusability_issues else "pass",
                detail=(
                    "; ".join(reusability_issues)
                    if reusability_issues
                    else "Candidate contains reusable support guidance."
                ),
                blocking=True,
            )
        )

        source_support = _candidate_source_support_score(candidate)
        checks.append(
            _check(
                code="source_support",
                label="Source support",
                status=(
                    "warn"
                    if source_support is not None
                    and source_support < SOURCE_SUPPORT_WARN_THRESHOLD
                    else "pass"
                ),
                detail=(
                    "Retrieved source snippets have low lexical overlap with the candidate answer "
                    f"({source_support:.2f}); verify the claim before promotion."
                    if source_support is not None
                    and source_support < SOURCE_SUPPORT_WARN_THRESHOLD
                    else (
                        f"Candidate answer is supported by retrieved source snippets ({source_support:.2f})."
                        if source_support is not None
                        else "No source-snippet content was available for lexical support scoring."
                    )
                ),
                blocking=False,
            )
        )

        feedback_example_count = _generator_feedback_example_count(generator_feedback)
        if feedback_example_count:
            feedback_tags = _feedback_tags(
                str(tag) for tag in (generator_feedback or {}).get("feedback_tags", [])
            )
            labels = ", ".join(_feedback_tag_label(tag) for tag in feedback_tags)
            checks.append(
                _check(
                    code="generator_feedback",
                    label="Prior review feedback",
                    status=("pass" if feedback_tags == ["good_generation"] else "warn"),
                    detail=(
                        f"{feedback_example_count} prior approved review(s) for this page/topic"
                        + (f" flagged {labels}." if labels else ".")
                    ),
                    blocking=False,
                )
            )

        if requires_cluster_synthesis:
            checks.append(
                _check(
                    code="cluster_synthesis_review",
                    label="Cluster synthesis review",
                    status="pass" if document_override_present else "fail",
                    detail=(
                        "An edited full document has been saved for this topic cluster."
                        if document_override_present
                        else (
                            "A generated synthesis draft is ready. Save the full "
                            "document to confirm human review before approval."
                        )
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
            bullets = [
                line if line.startswith("- ") else f"- {line}"
                for line in _lines(content)
                if line.strip()
            ]
            _append_with_gap(sections[section], bullets)
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


def _source_ref_links_for_refs(
    settings: Settings,
    refs: Iterable[str],
) -> Dict[str, str]:
    """Resolve durable source refs to verification links for admin previews."""
    slug_manager = SlugManager()
    normalized_refs = [str(ref).strip() for ref in refs if str(ref).strip()]
    numeric_faq_ids = [
        ref.removeprefix("faq:")
        for ref in normalized_refs
        if ref.startswith("faq:") and ref.removeprefix("faq:").isdigit()
    ]
    faq_id_links = _faq_id_links(settings, numeric_faq_ids, slug_manager)
    links: Dict[str, str] = {}

    for ref in normalized_refs:
        if ref.startswith("faq:"):
            value = ref.removeprefix("faq:").strip()
            if value.isdigit():
                href = faq_id_links.get(value)
                if href:
                    links[ref] = href
            elif slug_manager.validate_slug(value):
                links[ref] = f"/faq/{quote(value, safe='')}"
        elif ref.startswith("wiki:"):
            url = generate_wiki_url(ref.removeprefix("wiki:").strip())
            if url:
                links[ref] = url

    return links


def _faq_id_links(
    settings: Settings,
    faq_ids: Iterable[str],
    slug_manager: SlugManager,
) -> Dict[str, str]:
    unique_ids = sorted({faq_id for faq_id in faq_ids if faq_id.isdigit()}, key=int)
    if not unique_ids:
        return {}

    db_path = Path(settings.FAQ_DB_PATH)
    if not db_path.exists():
        return {}

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'faqs'"
            ).fetchone()
            if table_exists is None:
                return {}

            placeholders = ",".join("?" for _ in unique_ids)
            rows = conn.execute(
                f"SELECT id, question FROM faqs WHERE id IN ({placeholders})",
                unique_ids,
            ).fetchall()
    except sqlite3.Error:
        return {}

    links: Dict[str, str] = {}
    for row in rows:
        faq_id = str(row["id"])
        slug = slug_manager.generate_slug(str(row["question"] or ""), faq_id)
        links[faq_id] = f"/faq/{quote(slug, safe='')}"
    return links


def _durable_source_refs(refs: Iterable[str]) -> List[str]:
    """Keep only source refs that can be re-opened without stored chat logs."""
    return _dedupe(
        ref for ref in refs if not str(ref).strip().lower().startswith("support:")
    )


def _source_refs_from_markdown(markdown: str) -> List[str]:
    parsed = _read_markdown_text(markdown)
    if parsed is None:
        return []
    return _durable_source_refs(_string_list(parsed.frontmatter.get("source_refs")))


def _section_text_from_markdown(markdown: str, section_name: str) -> Optional[str]:
    parsed = _read_markdown_text(markdown)
    if parsed is None:
        return None
    _, sections = _split_sections(parsed.body)
    content = "\n".join(sections.get(section_name, [])).strip()
    return content or None


def _effective_source_refs(refs: Iterable[str], markdown: str) -> List[str]:
    return _durable_source_refs(
        [*_durable_source_refs(refs), *_source_refs_from_markdown(markdown)]
    )


def _sanitize_operations(operations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sanitized: List[Dict[str, Any]] = []
    for operation in operations:
        if operation.get("id") != "evidence-sources":
            sanitized.append(operation)
            continue

        refs = _source_refs_from_operation_content(str(operation.get("content") or ""))
        durable_refs = _durable_source_refs(refs)
        if durable_refs:
            sanitized.append(
                {
                    **operation,
                    "content": "\n".join(f"`{ref}`" for ref in durable_refs),
                }
            )
    return sanitized


def _source_refs_from_operation_content(content: str) -> List[str]:
    refs: List[str] = []
    for raw_part in re.split(r"[,\n]", content):
        ref = raw_part.strip().removeprefix("-").strip().strip("`").strip()
        if ref:
            refs.append(ref)
    return refs


def _proposal_has_cluster_context(
    proposal: KnowledgeUpdateProposal,
    cluster: Optional[KnowledgeTopicCluster],
) -> bool:
    if cluster is None:
        return True
    if proposal.document_markdown_override:
        return True
    return _operations_require_cluster_synthesis(
        proposal.operations
    ) and _operations_include_cluster_answer_units(proposal.operations, cluster)


def _operations_require_cluster_synthesis(operations: List[Dict[str, Any]]) -> bool:
    return any(operation.get("id") == "cluster-synthesis" for operation in operations)


def _cluster_applies_when(cluster: KnowledgeTopicCluster) -> str:
    questions = _cluster_question_units(cluster)
    if not questions:
        label = cluster.topic.replace("_", " ")
        return f"The user asks about {label}."
    return "\n".join(questions)


def _cluster_canonical_answer(cluster: KnowledgeTopicCluster) -> str:
    units = _cluster_answer_units(cluster)
    if not units:
        return ""
    if len(units) == 1:
        return units[0]
    return "\n".join(f"- {unit}" for unit in units)


def _cluster_last_change_summary(cluster: KnowledgeTopicCluster) -> str:
    return (
        f"Synthesized {cluster.size} related support discussions into one "
        "reviewable LLM Wiki page update through the Knowledge Updates admin workflow."
    )


def _cluster_synthesis_note(cluster: KnowledgeTopicCluster) -> str:
    return (
        f"Generated from {cluster.size} related support discussions (`{cluster.key}`). "
        "Save the full document to confirm that the synthesized page-level update is "
        "accurate, non-duplicative, and reusable before approval."
    )


def _operations_include_cluster_answer_units(
    operations: List[Dict[str, Any]],
    cluster: KnowledgeTopicCluster,
) -> bool:
    canonical = next(
        (
            str(operation.get("content") or "")
            for operation in operations
            if operation.get("id") == "canonical-answer"
        ),
        "",
    )
    if not canonical:
        return False
    canonical_fingerprint = _cluster_unit_fingerprint(canonical)
    return all(
        _cluster_unit_fingerprint(unit) in canonical_fingerprint
        for unit in _cluster_answer_units(cluster)
    )


def _cluster_question_units(cluster: KnowledgeTopicCluster) -> List[str]:
    return _dedupe_cluster_units(
        _clean_inline(candidate.edited_question_text or candidate.question_text)
        for candidate in cluster.candidates
    )


def _cluster_answer_units(cluster: KnowledgeTopicCluster) -> List[str]:
    units: List[str] = []
    for candidate in cluster.candidates:
        units.extend(
            _split_support_answer_units(
                candidate.edited_staff_answer or candidate.staff_answer
            )
        )
    return _dedupe_cluster_units(units)


def _split_support_answer_units(answer: str) -> List[str]:
    cleaned = _clean_block(answer)
    if not cleaned:
        return []
    lines = [
        line.strip().removeprefix("-").strip()
        for line in cleaned.splitlines()
        if line.strip()
    ]
    if len(lines) > 1:
        return [line for line in lines if line]
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", cleaned)
        if part.strip()
    ]


def _cluster_unit_fingerprint(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value).lower()))


def _dedupe_cluster_units(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        normalized = str(value).strip()
        fingerprint = _cluster_unit_fingerprint(normalized)
        if not normalized or not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append(normalized)
    return result


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _category_key(value: Any) -> Optional[str]:
    normalized = _optional_text(value)
    return _slugify(normalized) if normalized else None


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


def _feedback_tags(values: Iterable[str]) -> List[str]:
    return _dedupe(
        tag
        for value in values
        for tag in [str(value).strip()]
        if tag in FEEDBACK_TAG_LABELS
    )


def _feedback_tags_from_json(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return _feedback_tags(str(item) for item in parsed)


def _sqlite_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _section_diff_summary(
    before_markdown: str, after_markdown: str
) -> List[Dict[str, Any]]:
    before_sections = _sections_from_markdown(before_markdown)
    after_sections = _sections_from_markdown(after_markdown)
    section_names = _dedupe(
        [
            *[
                name
                for name in SECTION_ORDER
                if name in before_sections or name in after_sections
            ],
            *before_sections.keys(),
            *after_sections.keys(),
        ]
    )
    summary: List[Dict[str, Any]] = []
    for section_name in section_names:
        before = before_sections.get(section_name, "")
        after = after_sections.get(section_name, "")
        if before == after:
            continue
        summary.append(
            {
                "section": section_name,
                "before_chars": len(before),
                "after_chars": len(after),
            }
        )
    return summary


def _sections_from_markdown(markdown: str) -> Dict[str, str]:
    parsed = _read_markdown_text(markdown)
    body = parsed.body if parsed is not None else markdown
    _, sections = _split_sections(body)
    return {
        section_name: "\n".join(lines).strip()
        for section_name, lines in sections.items()
    }


def _section_diff_summary_from_json(raw: Optional[str]) -> List[Dict[str, Any]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    result: List[Dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        section = _optional_text(item.get("section"))
        if not section:
            continue
        result.append(
            {
                "section": section,
                "before_chars": _int_or_zero(item.get("before_chars")),
                "after_chars": _int_or_zero(item.get("after_chars")),
            }
        )
    return result


def _int_or_zero(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _empty_generator_feedback_context() -> Dict[str, Any]:
    return {
        "example_count": 0,
        "feedback_tags": [],
        "guidance": [],
        "notes": [],
        "examples": [],
    }


def _generator_feedback_context(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return _empty_generator_feedback_context()
    examples = raw.get("examples") if isinstance(raw.get("examples"), list) else []
    feedback_tags = (
        raw.get("feedback_tags") if isinstance(raw.get("feedback_tags"), list) else []
    )
    guidance = raw.get("guidance") if isinstance(raw.get("guidance"), list) else []
    notes = raw.get("notes") if isinstance(raw.get("notes"), list) else []
    return {
        "example_count": _int_or_zero(raw.get("example_count") or len(examples)),
        "feedback_tags": _feedback_tags(str(tag) for tag in feedback_tags),
        "guidance": _dedupe(str(item) for item in guidance),
        "notes": _dedupe(str(item) for item in notes),
        "examples": [item for item in examples if isinstance(item, dict)],
    }


def _generator_feedback_from_json(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return _empty_generator_feedback_context()
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return _empty_generator_feedback_context()
    return _generator_feedback_context(parsed)


def _generator_feedback_example_count(raw: Optional[Dict[str, Any]]) -> int:
    return _int_or_zero((raw or {}).get("example_count"))


def _guidance_for_feedback_tags(feedback_tags: Iterable[str]) -> List[str]:
    return _dedupe(
        FEEDBACK_TAG_GUIDANCE[tag]
        for tag in feedback_tags
        if tag in FEEDBACK_TAG_GUIDANCE
    )


def _feedback_tag_label(tag: str) -> str:
    return FEEDBACK_TAG_LABELS.get(tag, tag.replace("_", " "))


def _generator_feedback_note(raw: Optional[Dict[str, Any]]) -> str:
    context = _generator_feedback_context(raw)
    if not context["example_count"]:
        return ""
    lines = [
        (
            "Prior review feedback for this topic: "
            f"{context['example_count']} approved review example(s) are available."
        )
    ]
    for guidance in context["guidance"][:3]:
        lines.append(f"Generator guidance: {guidance}")
    for note in context["notes"][:2]:
        lines.append(f"Future generator note: {note}")
    return "\n".join(lines)


def _feedback_record_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "review_source": "proposal",
        "feedback_id": None,
        "proposal_id": row["id"],
        "candidate_id": row["candidate_id"],
        "target_page_id": row["target_page_id"],
        "target_page_title": row["target_page_title"],
        "proposal_kind": row["proposal_kind"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
        "review_notes": row["review_notes"],
        "last_change_summary": row["last_change_summary"],
        "feedback_tags": _feedback_tags_from_json(row["feedback_tags_json"]),
        "future_generator_note": row["future_generator_note"],
        "section_diff_summary": _section_diff_summary_from_json(
            row["section_diff_summary_json"]
        ),
        "generator_version": row["generator_version"] or GENERATOR_VERSION,
        "prompt_version": row["prompt_version"],
        "protocol": row["candidate_protocol"],
        "category": row["candidate_category"],
        "question_text": row["candidate_question"],
    }


def _external_feedback_record_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "review_source": row["source"] or "batch_import",
        "feedback_id": row["id"],
        "proposal_id": None,
        "candidate_id": None,
        "target_page_id": row["target_page_id"],
        "target_page_title": row["target_page_title"],
        "proposal_kind": "external_review",
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
        "review_notes": row["review_notes"],
        "last_change_summary": row["last_change_summary"],
        "feedback_tags": _feedback_tags_from_json(row["feedback_tags_json"]),
        "future_generator_note": row["future_generator_note"],
        "section_diff_summary": _section_diff_summary_from_json(
            row["section_diff_summary_json"]
        ),
        "generator_version": row["generator_version"] or GENERATOR_VERSION,
        "prompt_version": row["prompt_version"],
        "protocol": row["protocol"],
        "category": row["category"],
        "question_text": None,
        "source_refs": _durable_source_refs(
            _string_list(json.loads(row["source_refs_json"] or "[]"))
        ),
        "issues": _dedupe(
            str(issue) for issue in json.loads(row["issues_json"] or "[]")
        ),
        "page_path": row["page_path"],
        "source_batch_id": row["source_batch_id"],
    }


def _feedback_record_notes(record: Dict[str, Any]) -> List[str]:
    notes: List[str] = []
    future_note = _optional_text(record.get("future_generator_note"))
    if future_note:
        notes.append(future_note)
    review_notes = _optional_text(record.get("review_notes"))
    if review_notes:
        for line in review_notes.splitlines():
            cleaned = line.strip().removeprefix("-").strip()
            lower_cleaned = cleaned.lower()
            if lower_cleaned.startswith(
                "future generator guidance:"
            ) or lower_cleaned.startswith("future prompt guidance:"):
                notes.append(cleaned.split(":", 1)[1].strip())
    return notes


def _feedback_record_matches_candidate(
    record: Dict[str, Any],
    *,
    candidate: UnifiedFAQCandidate,
    target_page_id: str,
) -> bool:
    if record.get("target_page_id") == target_page_id:
        return True
    protocol = _optional_text(record.get("protocol"))
    category = _optional_text(record.get("category"))
    if not protocol or not category:
        return False
    return protocol == candidate.protocol and _slugify(category) == _slugify(
        candidate.category or ""
    )


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


def _candidate_reusability_issues(candidate: UnifiedFAQCandidate) -> List[str]:
    question = _clean_inline(candidate.edited_question_text or candidate.question_text)
    answer = _clean_block(candidate.edited_staff_answer or candidate.staff_answer)
    question_lower = question.lower()
    answer_lower = answer.lower()
    combined_lower = f"{question_lower} {answer_lower}"

    if not answer.strip():
        return ["Candidate has no reviewed staff answer."]

    issues: List[str] = []
    has_thin_answer = len(answer.strip()) < THIN_ANSWER_MIN_CHARS
    has_handoff_answer = any(
        pattern in answer_lower for pattern in THIN_ANSWER_PATTERNS
    )
    has_situational_question = any(
        term in combined_lower for term in SITUATIONAL_QUESTION_TERMS
    )

    if has_handoff_answer:
        issues.append("Answer is operational handoff guidance, not reusable knowledge.")
    if has_thin_answer and has_situational_question:
        issues.append("Answer is too thin for a situation-specific support case.")

    return issues


def _candidate_protocol_conflict(
    candidate: UnifiedFAQCandidate,
) -> Optional[tuple[str, float]]:
    protocol = candidate.protocol
    if not protocol or protocol == "all" or protocol not in VALID_PROTOCOLS:
        return None

    question_texts = _dedupe(
        _clean_inline(text)
        for text in (
            candidate.edited_question_text,
            candidate.original_user_question,
            candidate.question_text,
        )
        if text
    )
    for question_text in question_texts:
        detected_protocol, confidence = _PROTOCOL_DETECTOR.detect_protocol_from_text(
            question_text
        )
        if (
            detected_protocol
            and detected_protocol != protocol
            and confidence >= PROTOCOL_CONFLICT_CONFIDENCE
        ):
            return detected_protocol, confidence
    return None


def _candidate_source_support_score(
    candidate: UnifiedFAQCandidate,
) -> Optional[float]:
    sources = _parse_sources(candidate.generated_answer_sources)
    source_text = " ".join(
        str(source.get("content") or "")
        for source in sources
        if isinstance(source, dict)
    )
    if not source_text.strip():
        return None

    answer_tokens = _source_support_tokens(
        candidate.edited_staff_answer or candidate.staff_answer
    )
    source_tokens = _source_support_tokens(source_text)
    if not answer_tokens or not source_tokens:
        return None
    return len(answer_tokens & source_tokens) / len(answer_tokens)


def _source_support_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", str(value or "").lower())
        if token not in SOURCE_SUPPORT_STOPWORDS
    }


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

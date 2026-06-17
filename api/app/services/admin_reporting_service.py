"""Support-admin reporting over existing review audit data."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

REVIEWED_STATUSES = {"approved", "rejected"}


class SupportReportingService:
    """Build compensation-ready reports from support-admin review decisions."""

    def __init__(self, *, db_path: str) -> None:
        self.db_path = db_path

    def build_support_work_report(
        self,
        *,
        start_date: date,
        end_date: date,
        reviewer: Optional[str] = None,
        period_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return reviewed LLM Wiki work for an inclusive UTC date window."""
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")

        rows = self._fetch_reviewed_llm_wiki_rows(
            start_date=start_date,
            end_date=end_date,
            reviewer=reviewer,
        )
        summary = _build_summary(rows)
        reviewers = _build_reviewer_breakdown(rows)
        pages = _build_page_breakdown(rows)
        items = [_row_to_item(row) for row in rows]
        period = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "period_label": _clean_optional(period_label),
            "reviewer": _clean_optional(reviewer),
            "date_basis": "knowledge_update_proposals.reviewed_at UTC day",
        }
        report_markdown = _build_report_markdown(
            period=period,
            summary=summary,
            reviewers=reviewers,
            pages=pages,
        )

        return {
            "period": period,
            "summary": summary,
            "reviewers": reviewers,
            "pages": pages,
            "items": items,
            "future_sections": [
                {
                    "key": "handled_escalations",
                    "label": "Handled escalations",
                    "status": "planned",
                    "total_reviews": 0,
                }
            ],
            "report_markdown": report_markdown,
        }

    def _fetch_reviewed_llm_wiki_rows(
        self,
        *,
        start_date: date,
        end_date: date,
        reviewer: Optional[str],
    ) -> list[sqlite3.Row]:
        if not Path(self.db_path).exists():
            return []

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            if not _table_exists(conn, "knowledge_update_proposals"):
                return []

            has_candidates = _table_exists(conn, "unified_faq_candidates")
            reviewer_filter = _clean_optional(reviewer)
            params: list[Any] = [start_date.isoformat(), end_date.isoformat()]
            reviewer_clause = ""
            if reviewer_filter:
                reviewer_clause = "AND lower(coalesce(p.reviewed_by, '')) = lower(?)"
                params.append(reviewer_filter)

            if has_candidates:
                query = f"""
                    SELECT
                        p.id,
                        p.candidate_id,
                        p.target_page_id,
                        p.target_page_title,
                        p.proposal_kind,
                        p.status,
                        p.reviewed_by,
                        p.reviewed_at,
                        p.rejection_reason,
                        c.source,
                        c.routing,
                        c.protocol,
                        c.category,
                        c.question_text,
                        c.staff_sender
                    FROM knowledge_update_proposals p
                    LEFT JOIN unified_faq_candidates c ON c.id = p.candidate_id
                    WHERE p.status IN ('approved', 'rejected')
                      AND p.reviewed_at IS NOT NULL
                      AND date(p.reviewed_at) >= date(?)
                      AND date(p.reviewed_at) <= date(?)
                      {reviewer_clause}
                    ORDER BY p.reviewed_at DESC, p.id DESC
                """
            else:
                query = f"""
                    SELECT
                        p.id,
                        p.candidate_id,
                        p.target_page_id,
                        p.target_page_title,
                        p.proposal_kind,
                        p.status,
                        p.reviewed_by,
                        p.reviewed_at,
                        p.rejection_reason,
                        NULL AS source,
                        NULL AS routing,
                        NULL AS protocol,
                        NULL AS category,
                        NULL AS question_text,
                        NULL AS staff_sender
                    FROM knowledge_update_proposals p
                    WHERE p.status IN ('approved', 'rejected')
                      AND p.reviewed_at IS NOT NULL
                      AND date(p.reviewed_at) >= date(?)
                      AND date(p.reviewed_at) <= date(?)
                      {reviewer_clause}
                    ORDER BY p.reviewed_at DESC, p.id DESC
                """
            return list(conn.execute(query, params).fetchall())
        finally:
            conn.close()


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _build_summary(rows: list[sqlite3.Row]) -> Dict[str, int]:
    approved = sum(1 for row in rows if row["status"] == "approved")
    rejected = sum(1 for row in rows if row["status"] == "rejected")
    page_ids = {_page_id(row) for row in rows}
    new_pages = sum(1 for row in rows if row["proposal_kind"] == "create_new")
    existing_updates = sum(
        1 for row in rows if row["proposal_kind"] == "update_existing"
    )
    return {
        "total_reviews": len(rows),
        "approved": approved,
        "rejected": rejected,
        "pages_touched": len(page_ids),
        "new_pages": new_pages,
        "existing_page_updates": existing_updates,
    }


def _build_reviewer_breakdown(rows: list[sqlite3.Row]) -> list[Dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        reviewer = row["reviewed_by"] or "unknown"
        entry = grouped.setdefault(
            reviewer,
            {
                "reviewer": reviewer,
                "total_reviews": 0,
                "approved": 0,
                "rejected": 0,
            },
        )
        _increment_status(entry, row["status"])
    return sorted(
        grouped.values(),
        key=lambda item: (-int(item["total_reviews"]), str(item["reviewer"]).lower()),
    )


def _build_page_breakdown(rows: list[sqlite3.Row]) -> list[Dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        page_id = _page_id(row)
        entry = grouped.setdefault(
            page_id,
            {
                "page_id": page_id,
                "title": row["target_page_title"] or page_id,
                "total_reviews": 0,
                "approved": 0,
                "rejected": 0,
                "last_reviewed_at": row["reviewed_at"],
                "proposal_kinds": defaultdict(int),
            },
        )
        _increment_status(entry, row["status"])
        entry["proposal_kinds"][row["proposal_kind"] or "unknown"] += 1
        if (row["reviewed_at"] or "") > (entry["last_reviewed_at"] or ""):
            entry["last_reviewed_at"] = row["reviewed_at"]

    normalized: list[Dict[str, Any]] = []
    for entry in grouped.values():
        normalized.append(
            {
                **entry,
                "proposal_kinds": dict(entry["proposal_kinds"]),
            }
        )
    return sorted(
        normalized,
        key=lambda item: (
            -int(item["total_reviews"]),
            str(item["title"]).lower(),
            str(item["page_id"]),
        ),
    )


def _increment_status(entry: dict[str, Any], status: str) -> None:
    entry["total_reviews"] += 1
    if status in REVIEWED_STATUSES:
        entry[status] += 1


def _row_to_item(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "proposal_id": row["id"],
        "candidate_id": row["candidate_id"],
        "target_page_id": _page_id(row),
        "target_page_title": row["target_page_title"] or _page_id(row),
        "proposal_kind": row["proposal_kind"],
        "status": row["status"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
        "rejection_reason": row["rejection_reason"],
        "source": row["source"],
        "routing": row["routing"],
        "protocol": row["protocol"],
        "category": row["category"],
        "question_text": row["question_text"],
        "staff_sender": row["staff_sender"],
    }


def _page_id(row: sqlite3.Row) -> str:
    return row["target_page_id"] or f"candidate-{row['candidate_id']}"


def _clean_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _build_report_markdown(
    *,
    period: Dict[str, Any],
    summary: Dict[str, int],
    reviewers: Iterable[Dict[str, Any]],
    pages: Iterable[Dict[str, Any]],
) -> str:
    lines = [
        "# Support admin work report",
        "",
        f"Period: {period['start_date']} to {period['end_date']}",
    ]
    if period.get("period_label"):
        lines.append(f"Compensation period: {period['period_label']}")
    if period.get("reviewer"):
        lines.append(f"Reviewer filter: {period['reviewer']}")
    lines.extend(
        [
            "",
            "## LLM Wiki reviews",
            "",
            f"- Total reviewed changes: {summary['total_reviews']}",
            f"- Approved: {summary['approved']}",
            f"- Rejected: {summary['rejected']}",
            f"- Pages touched: {summary['pages_touched']}",
            f"- New pages: {summary['new_pages']}",
            f"- Existing page updates: {summary['existing_page_updates']}",
            "",
            "## Reviewer breakdown",
            "",
        ]
    )
    reviewer_rows = list(reviewers)
    if reviewer_rows:
        for reviewer in reviewer_rows:
            lines.append(
                "- "
                f"{reviewer['reviewer']}: "
                f"{reviewer['total_reviews']} reviewed "
                f"({reviewer['approved']} approved, {reviewer['rejected']} rejected)"
            )
    else:
        lines.append("- No reviewed LLM Wiki changes in this period.")

    lines.extend(["", "## Pages reviewed", ""])
    page_rows = list(pages)
    if page_rows:
        for page in page_rows:
            lines.append(
                "- "
                f"{page['title']} (`{page['page_id']}`): "
                f"{page['total_reviews']} reviewed "
                f"({page['approved']} approved, {page['rejected']} rejected)"
            )
    else:
        lines.append("- No LLM Wiki pages reviewed in this period.")

    return "\n".join(lines)

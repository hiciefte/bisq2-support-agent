#!/usr/bin/env python3
"""Audit production knowledge-update candidates from an exported JSON snapshot.

The script intentionally works from a read-only export. It replays proposal
generation in a temporary data directory so candidate checks use the same
service logic as the admin backend, then writes reviewable JSON/CSV/Markdown
artifacts without copying production data into the repository.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import tempfile
from collections import Counter
from dataclasses import MISSING, fields
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.config import Settings  # noqa: E402
from app.services.knowledge_updates.candidate_rework_triage import (  # noqa: E402
    CandidateReworkTriageService,
)
from app.services.knowledge_updates.llm_wiki_update_service import (  # noqa: E402
    KnowledgeUpdateService,
)
from app.services.knowledge_updates.topic_clusters import (  # noqa: E402
    TOKEN_STOPWORDS,
    TOPIC_CLUSTER_MAX_SIZE,
    TOPIC_CLUSTER_MIN_SIZE,
    build_exact_clusters,
    build_knowledge_review_items,
    exact_cluster_key,
    topic_cluster_ids,
    topic_cluster_key,
)
from app.services.training.unified_repository import UnifiedFAQCandidate  # noqa: E402

CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def main() -> None:
    args = _parse_args()
    export = _read_json(args.export)
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates = [
        _candidate_from_dict(raw)
        for raw in export.get("pending_candidates", [])
        if isinstance(raw, dict)
    ]
    exact_clusters = build_exact_clusters(candidates)
    topic_clusters = topic_cluster_ids(candidates)

    with tempfile.TemporaryDirectory(prefix="bisq-knowledge-audit-") as tmp:
        data_dir = Path(tmp)
        _write_exported_pages(export, data_dir)
        service = KnowledgeUpdateService(
            settings=Settings(DATA_DIR=str(data_dir)),
            db_path=str(data_dir / "unified_training.db"),
        )
        admin_cluster_index = _admin_cluster_index(service, candidates)

        candidate_rows = [
            _audit_candidate(
                service,
                candidate,
                exact_clusters,
                topic_clusters,
                admin_cluster_index,
            )
            for candidate in candidates
        ]
        rework_triage = CandidateReworkTriageService(service).build(
            candidates,
        ).to_response()

    page_rows = _audit_pages(export)
    proposal_rows = _audit_existing_proposals(export)
    summary = _summary(candidate_rows, page_rows, proposal_rows, rework_triage)

    _write_json(out_dir / "knowledge_candidate_audit.json", candidate_rows)
    _write_json(out_dir / "knowledge_page_audit.json", page_rows)
    _write_json(out_dir / "knowledge_proposal_audit.json", proposal_rows)
    _write_json(out_dir / "knowledge_rework_triage.json", rework_triage)
    _write_csv(out_dir / "knowledge_candidate_audit.csv", candidate_rows)
    (out_dir / "knowledge_candidate_audit.md").write_text(
        _render_markdown(
            summary,
            candidate_rows,
            page_rows,
            proposal_rows,
            rework_triage,
        ),
        encoding="utf-8",
    )

    print(f"Wrote audit artifacts to {out_dir}")
    print(json.dumps(summary, indent=2, sort_keys=True))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--export",
        type=Path,
        required=True,
        help="Path to production export JSON.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Directory for JSON/CSV/Markdown audit artifacts. Defaults to a private "
            "random temporary directory."
        ),
    )
    args = parser.parse_args()
    if args.output_dir is None:
        args.output_dir = Path(tempfile.mkdtemp(prefix="bisq_support_knowledge_audit_"))
    return args


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "candidate_id",
        "recommendation",
        "routing",
        "source",
        "protocol",
        "category",
        "proposal_kind",
        "target_page_id",
        "exact_cluster_size",
        "topic_cluster_key",
        "topic_cluster_size",
        "admin_cluster_key",
        "admin_cluster_size",
        "blocking_failures",
        "warnings",
        "question",
        "answer",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "candidate_id": row["candidate_id"],
                    "recommendation": _csv_safe(row["recommendation"]),
                    "routing": _csv_safe(row["routing"]),
                    "source": _csv_safe(row["source"]),
                    "protocol": _csv_safe(row["protocol"]),
                    "category": _csv_safe(row["category"]),
                    "proposal_kind": _csv_safe(row["proposal_kind"]),
                    "target_page_id": _csv_safe(row["target_page_id"]),
                    "exact_cluster_size": row["exact_cluster_size"],
                    "topic_cluster_key": _csv_safe(row["topic_cluster_key"]),
                    "topic_cluster_size": row["topic_cluster_size"],
                    "admin_cluster_key": _csv_safe(row.get("admin_cluster_key")),
                    "admin_cluster_size": row.get("admin_cluster_size", 0),
                    "blocking_failures": _csv_safe("; ".join(row["blocking_failures"])),
                    "warnings": _csv_safe("; ".join(row["warnings"])),
                    "question": _csv_safe(row["question"]),
                    "answer": _csv_safe(row["answer"]),
                }
            )


def _csv_safe(value: Any) -> str:
    text = "" if value is None else str(value)
    if text and text.lstrip().startswith(CSV_FORMULA_PREFIXES):
        return "'" + text
    return text


def _candidate_from_dict(raw: dict[str, Any]) -> UnifiedFAQCandidate:
    candidate_fields = {field.name: field for field in fields(UnifiedFAQCandidate)}
    required = [
        name
        for name, field in candidate_fields.items()
        if field.default is MISSING and field.default_factory is MISSING
    ]
    missing_required = [name for name in required if raw.get(name) is None]
    if missing_required:
        missing = ", ".join(sorted(missing_required))
        raise ValueError(f"Candidate export is missing required fields: {missing}")

    values = {
        name: raw[name]
        for name in candidate_fields
        if name in raw and raw[name] is not None
    }
    for boolean_field in ("is_calibration_sample", "has_correction"):
        if boolean_field in values:
            values[boolean_field] = bool(values[boolean_field])
    return UnifiedFAQCandidate(**values)


def _write_exported_pages(export: dict[str, Any], data_dir: Path) -> None:
    pages_dir = data_dir / "knowledge" / "llm_wiki" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    pages = export.get("llm_wiki_pages")
    if not isinstance(pages, list):
        raise ValueError("Export is missing llm_wiki_pages list")

    skipped = 0
    written = 0
    for page in pages:
        if not isinstance(page, dict):
            skipped += 1
            continue
        name = str(page.get("name") or "").strip()
        markdown = str(page.get("markdown") or "").strip()
        if not name or not markdown:
            skipped += 1
            continue
        safe_name = Path(name).name
        (pages_dir / safe_name).write_text(markdown + "\n", encoding="utf-8")
        written += 1

    if skipped:
        raise ValueError(f"Skipped {skipped} invalid LLM Wiki page export rows")
    if written == 0:
        raise ValueError("No LLM Wiki pages were materialized from the export")


def _admin_cluster_index(
    service: KnowledgeUpdateService,
    candidates: list[UnifiedFAQCandidate],
) -> dict[int, dict[str, Any]]:
    index: dict[int, dict[str, Any]] = {}
    items = build_knowledge_review_items(
        candidates,
        service.is_candidate_reviewable,
        cluster_key=service.review_cluster_key,
    )
    for item in items:
        if item.cluster is None:
            candidate_ids = [item.candidate.id]
            key = service.review_cluster_key(item.candidate)
        else:
            candidate_ids = item.cluster.candidate_ids
            key = item.cluster.key
        for candidate_id in candidate_ids:
            index[candidate_id] = {
                "admin_cluster_key": key,
                "admin_cluster_size": len(candidate_ids),
                "admin_cluster_candidate_ids": candidate_ids[:25],
            }
    return index


def _audit_candidate(
    service: KnowledgeUpdateService,
    candidate: UnifiedFAQCandidate,
    exact_clusters: dict[str, list[int]],
    topic_clusters: dict[str, list[int]],
    admin_cluster_index: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    try:
        proposal = service.get_or_create_proposal(candidate=candidate)
        checks = proposal.checks
        proposal_kind = proposal.proposal_kind
        target_page_id = proposal.target_page_id
        target_page_title = proposal.target_page_title
    except (sqlite3.Error, ValueError) as exc:
        checks = [
            {
                "code": "proposal_generation",
                "label": "Proposal generation",
                "status": "fail",
                "detail": str(exc),
                "blocking": True,
            }
        ]
        proposal_kind = None
        target_page_id = None
        target_page_title = None

    blocking_failures = [
        str(check.get("label"))
        for check in checks
        if check.get("blocking") and check.get("status") == "fail"
    ]
    warnings = [
        str(check.get("label")) for check in checks if check.get("status") == "warn"
    ]
    cluster_key = exact_cluster_key(candidate)
    cluster_ids = exact_clusters.get(cluster_key, [])
    topic_key = topic_cluster_key(candidate)
    topic_ids = topic_clusters.get(topic_key, [])
    admin_cluster = admin_cluster_index.get(
        candidate.id,
        {
            "admin_cluster_key": None,
            "admin_cluster_size": 0,
            "admin_cluster_candidate_ids": [],
        },
    )
    recommendation = _recommendation(
        candidate=candidate,
        blocking_failures=blocking_failures,
        warnings=warnings,
        cluster_size=len(cluster_ids),
        admin_cluster_size=int(admin_cluster["admin_cluster_size"]),
        proposal_kind=proposal_kind,
    )
    return {
        "candidate_id": candidate.id,
        "recommendation": recommendation,
        "routing": candidate.routing,
        "source": candidate.source,
        "protocol": candidate.protocol,
        "category": candidate.category,
        "proposal_kind": proposal_kind,
        "target_page_id": target_page_id,
        "target_page_title": target_page_title,
        "exact_cluster_key": cluster_key,
        "exact_cluster_size": len(cluster_ids),
        "exact_cluster_candidate_ids": cluster_ids[:25],
        "topic_cluster_key": topic_key,
        "topic_cluster_size": len(topic_ids),
        "topic_cluster_candidate_ids": topic_ids[:25],
        "admin_cluster_key": admin_cluster["admin_cluster_key"],
        "admin_cluster_size": admin_cluster["admin_cluster_size"],
        "admin_cluster_candidate_ids": admin_cluster["admin_cluster_candidate_ids"],
        "blocking_failures": blocking_failures,
        "warnings": warnings,
        "check_details": checks,
        "question": _clean(candidate.edited_question_text or candidate.question_text),
        "answer": _clean(candidate.edited_staff_answer or candidate.staff_answer),
        "source_titles": _source_titles(candidate.generated_answer_sources),
        "contradiction_score": candidate.contradiction_score,
        "hallucination_risk": candidate.hallucination_risk,
        "generation_confidence": candidate.generation_confidence,
    }


def _recommendation(
    *,
    candidate: UnifiedFAQCandidate,
    blocking_failures: list[str],
    warnings: list[str],
    cluster_size: int,
    admin_cluster_size: int,
    proposal_kind: str | None,
) -> str:
    if blocking_failures:
        return "reject_or_rework"
    if cluster_size > 1:
        return "merge_duplicate_cluster"
    if admin_cluster_size >= TOPIC_CLUSTER_MIN_SIZE:
        return "merge_topic_cluster"
    if (candidate.contradiction_score or 0.0) >= 0.35:
        return "manual_full_review"
    if (candidate.hallucination_risk or 0.0) >= 0.45:
        return "manual_full_review"
    if warnings:
        return "manual_spot_check"
    if proposal_kind == "update_existing":
        return "review_update"
    return "review_new_page"


def _audit_pages(export: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for page in export.get("llm_wiki_pages", []):
        if not isinstance(page, dict):
            continue
        body = str(page.get("body") or "")
        source_refs = (
            page.get("source_refs") if isinstance(page.get("source_refs"), list) else []
        )
        flags = []
        if len(source_refs) > 12:
            flags.append("too_many_source_refs")
        if "Derived from reviewed" in body:
            flags.append("support_discussion_review_notes")
        if re.search(r"\n{4,}", body):
            flags.append("excess_blank_lines")
        evidence_section = _section(body, "Evidence / Sources")
        comma_ref_lines = [
            line
            for line in evidence_section.splitlines()
            if line.strip().startswith("- ")
            and line.count("faq:") + line.count("wiki:") > 2
        ]
        if comma_ref_lines:
            flags.append("dense_unreadable_evidence_line")
        rows.append(
            {
                "page_id": page.get("id"),
                "title": page.get("title"),
                "status": page.get("status"),
                "protocol": page.get("protocol"),
                "source_ref_count": len(source_refs),
                "flags": flags,
                "recommendation": (
                    "curate_before_active" if flags else "keep_reviewable"
                ),
            }
        )
    return rows


def _audit_existing_proposals(export: dict[str, Any]) -> list[dict[str, Any]]:
    candidates_by_id = {
        int(candidate["id"]): candidate
        for candidate in export.get("all_candidates", [])
        if isinstance(candidate, dict) and candidate.get("id") is not None
    }
    rows = []
    for proposal in export.get("knowledge_update_proposals", []):
        if not isinstance(proposal, dict):
            continue
        candidate = candidates_by_id.get(int(proposal.get("candidate_id") or 0))
        target = str(proposal.get("target_page_id") or "")
        candidate_data = candidate or {}
        question = str(
            candidate_data.get("edited_question_text")
            or candidate_data.get("question_text")
            or ""
        )
        answer = str(
            candidate_data.get("edited_staff_answer")
            or candidate_data.get("staff_answer")
            or ""
        )
        overlap = _token_overlap(
            f"{target} {proposal.get('target_page_title')}", f"{question} {answer}"
        )
        flags = []
        if overlap < 0.10:
            flags.append("weak_target_overlap")
        if proposal.get("status") == "approved" and flags:
            flags.append("approved_with_target_risk")
        rows.append(
            {
                "proposal_id": proposal.get("id"),
                "candidate_id": proposal.get("candidate_id"),
                "status": proposal.get("status"),
                "target_page_id": target,
                "target_page_title": proposal.get("target_page_title"),
                "target_overlap": round(overlap, 4),
                "flags": flags,
                "question": _clean(question),
                "answer": _clean(answer),
            }
        )
    return rows


def _summary(
    candidate_rows: list[dict[str, Any]],
    page_rows: list[dict[str, Any]],
    proposal_rows: list[dict[str, Any]],
    rework_triage: dict[str, Any],
) -> dict[str, Any]:
    recommendations = Counter(row["recommendation"] for row in candidate_rows)
    protocols = Counter(str(row["protocol"]) for row in candidate_rows)
    target_pages = Counter(
        row["target_page_id"] for row in candidate_rows if row["target_page_id"]
    )
    blocking_failures = Counter(
        failure
        for row in candidate_rows
        for failure in row.get("blocking_failures", [])
    )
    page_flags = Counter(flag for row in page_rows for flag in row["flags"])
    proposal_flags = Counter(flag for row in proposal_rows for flag in row["flags"])
    duplicate_clusters = sum(
        1
        for row in candidate_rows
        if row["exact_cluster_size"] > 1
        and row["exact_cluster_candidate_ids"][0] == row["candidate_id"]
    )
    broad_topic_clusters = sum(
        1
        for row in candidate_rows
        if row["topic_cluster_size"] >= TOPIC_CLUSTER_MIN_SIZE
        and row["topic_cluster_candidate_ids"][0] == row["candidate_id"]
    )
    admin_clusters = sum(
        1
        for row in candidate_rows
        if row["admin_cluster_size"] >= TOPIC_CLUSTER_MIN_SIZE
        and row["admin_cluster_candidate_ids"][0] == row["candidate_id"]
    )
    top_topic_clusters = Counter(
        row["topic_cluster_key"] for row in candidate_rows
    ).most_common(20)
    admin_cluster_sizes = {
        str(row["admin_cluster_key"]): row["admin_cluster_size"]
        for row in candidate_rows
        if row["admin_cluster_size"] >= TOPIC_CLUSTER_MIN_SIZE
        and row["admin_cluster_candidate_ids"][0] == row["candidate_id"]
    }
    top_admin_clusters = sorted(
        admin_cluster_sizes.items(),
        key=lambda entry: entry[1],
        reverse=True,
    )[:20]
    return {
        "candidate_count": len(candidate_rows),
        "recommendations": dict(recommendations),
        "protocols": dict(protocols),
        "top_target_pages": dict(target_pages.most_common(10)),
        "blocking_failures": dict(blocking_failures),
        "duplicate_clusters": duplicate_clusters,
        "topic_clusters": broad_topic_clusters,
        "admin_clusters": admin_clusters,
        "top_topic_clusters": dict(top_topic_clusters),
        "top_admin_clusters": dict(top_admin_clusters),
        "page_count": len(page_rows),
        "page_flags": dict(page_flags),
        "proposal_count": len(proposal_rows),
        "proposal_flags": dict(proposal_flags),
        "rework_triage": {
            "total_blocked": rework_triage.get("total_blocked", 0),
            "group_count": rework_triage.get("group_count", 0),
            "action_counts": rework_triage.get("action_counts", {}),
            "issue_counts": rework_triage.get("issue_counts", {}),
        },
    }


def _render_markdown(
    summary: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
    page_rows: list[dict[str, Any]],
    proposal_rows: list[dict[str, Any]],
    rework_triage: dict[str, Any],
) -> str:
    lines = [
        "# Knowledge Update Candidate Audit",
        "",
        "## Summary",
        "",
        f"- Pending candidates: {summary['candidate_count']}",
        f"- Duplicate exact clusters: {summary['duplicate_clusters']}",
        f"- Broad diagnostic topic clusters with {TOPIC_CLUSTER_MIN_SIZE}+ candidates: {summary['topic_clusters']}",
        f"- Admin clusters with {TOPIC_CLUSTER_MIN_SIZE}-{TOPIC_CLUSTER_MAX_SIZE} candidates: {summary['admin_clusters']}",
        f"- LLM Wiki pages in export: {summary['page_count']}",
        f"- Existing proposals in export: {summary['proposal_count']}",
        f"- Blocked candidates grouped for rework: {summary['rework_triage']['total_blocked']} candidates in {summary['rework_triage']['group_count']} group(s)",
        "",
        "## Recommendations",
        "",
    ]
    for key, count in sorted(summary["recommendations"].items()):
        lines.append(f"- {key}: {count}")

    lines.extend(["", "## AI-Assisted Rework Triage", ""])
    for key, count in sorted(summary["rework_triage"]["action_counts"].items()):
        lines.append(f"- {key}: {count}")

    lines.extend(["", "### Top Rework Groups", ""])
    for group in rework_triage.get("groups", [])[:20]:
        size = int(group.get("size") or 0)
        candidate_label = "candidate" if size == 1 else "candidates"
        examples = group.get("examples") or []
        example_question = ""
        if examples and isinstance(examples[0], dict):
            example_question = str(examples[0].get("question") or "")[:140]
        lines.append(
            f"- {size} {candidate_label} `{group.get('action')}` "
            f"-> `{group.get('target_page_id')}` "
            f"({', '.join(group.get('issue_codes') or [])}): {example_question}"
        )

    lines.extend(["", "## Blocking Failures", ""])
    for key, count in sorted(summary["blocking_failures"].items()):
        lines.append(f"- {key}: {count}")

    lines.extend(["", "## Page Hygiene Flags", ""])
    for key, count in sorted(summary["page_flags"].items()):
        lines.append(f"- {key}: {count}")

    lines.extend(["", "## Existing Proposal Risks", ""])
    for row in proposal_rows:
        if not row["flags"]:
            continue
        lines.append(
            f"- Candidate {row['candidate_id']} -> `{row['target_page_id']}`: "
            f"{', '.join(row['flags'])}"
        )

    lines.extend(["", "## Top Duplicate Clusters", ""])
    seen_clusters: set[str] = set()
    duplicate_rows = [
        row
        for row in candidate_rows
        if row["exact_cluster_size"] > 1
        and row["exact_cluster_key"] not in seen_clusters
        and not seen_clusters.add(row["exact_cluster_key"])
    ]
    for row in sorted(
        duplicate_rows,
        key=lambda item: item["exact_cluster_size"],
        reverse=True,
    )[:20]:
        ids = ", ".join(str(cid) for cid in row["exact_cluster_candidate_ids"][:12])
        lines.append(
            f"- {row['exact_cluster_size']} candidates [{ids}] "
            f"{row['protocol']}/{row['category']}: {row['question'][:140]}"
        )

    lines.extend(["", "## Top Topic Clusters", ""])
    seen_topics: set[str] = set()
    topic_rows = [
        row
        for row in candidate_rows
        if row["topic_cluster_size"] >= TOPIC_CLUSTER_MIN_SIZE
        and row["topic_cluster_key"] not in seen_topics
        and not seen_topics.add(row["topic_cluster_key"])
    ]
    for row in sorted(
        topic_rows,
        key=lambda item: item["topic_cluster_size"],
        reverse=True,
    )[:20]:
        ids = ", ".join(str(cid) for cid in row["topic_cluster_candidate_ids"][:12])
        lines.append(
            f"- {row['topic_cluster_size']} candidates `{row['topic_cluster_key']}` "
            f"[{ids}] example: {row['question'][:140]}"
        )

    lines.extend(["", "## Top Admin Clusters", ""])
    seen_admin_clusters: set[str] = set()
    admin_rows = [
        row
        for row in candidate_rows
        if row["admin_cluster_size"] >= TOPIC_CLUSTER_MIN_SIZE
        and row["admin_cluster_key"] not in seen_admin_clusters
        and not seen_admin_clusters.add(row["admin_cluster_key"])
    ]
    for row in sorted(
        admin_rows,
        key=lambda item: item["admin_cluster_size"],
        reverse=True,
    )[:20]:
        ids = ", ".join(str(cid) for cid in row["admin_cluster_candidate_ids"][:12])
        lines.append(
            f"- {row['admin_cluster_size']} candidates `{row['admin_cluster_key']}` "
            f"[{ids}] example: {row['question'][:140]}"
        )

    lines.extend(["", "## Candidate Rows Requiring Rework", ""])
    for row in candidate_rows:
        if row["recommendation"] != "reject_or_rework":
            continue
        failures = ", ".join(row["blocking_failures"])
        lines.append(
            f"- Candidate {row['candidate_id']} ({row['protocol']}, "
            f"{row['category']}): {failures} | {row['question'][:150]}"
        )

    lines.append("")
    return "\n".join(lines)


def _source_titles(raw_sources: str | None) -> list[str]:
    if not raw_sources:
        return []
    try:
        parsed = json.loads(raw_sources)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    titles = []
    for source in parsed:
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or "").strip()
        source_type = str(source.get("type") or source.get("category") or "").strip()
        if title:
            titles.append(f"{source_type}:{title}" if source_type else title)
    return titles[:12]


def _section(body: str, section_name: str) -> str:
    pattern = rf"^## {re.escape(section_name)}\n(?P<body>.*?)(?=^## |\Z)"
    match = re.search(pattern, body, flags=re.MULTILINE | re.DOTALL)
    return match.group("body") if match else ""


def _token_overlap(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), 1)


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", str(value).lower())
        if token not in TOKEN_STOPWORDS
    }


def _clean(value: str) -> str:
    return " ".join(str(value or "").split())


if __name__ == "__main__":
    main()

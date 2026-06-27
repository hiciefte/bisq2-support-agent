#!/usr/bin/env python3
"""Import externally reviewed LLM Wiki markdown and mine generator feedback."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.config import Settings  # noqa: E402
from app.services.knowledge_updates.llm_wiki_review_importer import (  # noqa: E402
    ReviewedLLMWikiBatchImporter,
    batch_result_to_json,
)
from app.services.knowledge_updates.llm_wiki_update_service import (  # noqa: E402
    KnowledgeUpdateService,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = Settings(DATA_DIR=str(args.data_dir)) if args.data_dir else Settings()
    original_pages_dir = args.original_pages_dir or Path(settings.LLM_WIKI_DIR_PATH)
    service = None
    if not args.no_record_feedback:
        db_path = args.db_path or Path(settings.DATA_DIR) / "unified_training.db"
        service = KnowledgeUpdateService(settings=settings, db_path=str(db_path))

    importer = ReviewedLLMWikiBatchImporter(
        original_pages_dir=original_pages_dir,
        knowledge_update_service=service,
    )
    result = importer.import_batch(
        reviewed_path=args.reviewed_path,
        reviewer=args.reviewer,
        reviewed_at=args.reviewed_at,
        output_dir=args.output_dir,
        apply=args.apply,
        record_feedback=not args.no_record_feedback,
    )
    rendered = batch_result_to_json(result)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 1 if result.invalid_pages or result.admin_section_leakage else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reviewed-path",
        type=Path,
        required=True,
        help="Directory or .zip file containing human-reviewed LLM Wiki markdown.",
    )
    parser.add_argument(
        "--reviewer",
        required=True,
        help="Reviewer name to write into reviewed_by and feedback records.",
    )
    parser.add_argument(
        "--reviewed-at",
        required=True,
        help="ISO date or timestamp to write into reviewed_at and feedback records.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Data directory for Settings. Defaults to configured environment.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="SQLite DB for generator feedback. Defaults to DATA_DIR/unified_training.db.",
    )
    parser.add_argument(
        "--original-pages-dir",
        type=Path,
        default=None,
        help="Original generated LLM Wiki pages. Defaults to Settings.LLM_WIKI_DIR_PATH.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Where normalized reviewed pages are written when --apply is set.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional path for the JSON import report.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write normalized reviewed pages to --output-dir or the original pages dir.",
    )
    parser.add_argument(
        "--no-record-feedback",
        action="store_true",
        help="Do not write mined review feedback into SQLite.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())

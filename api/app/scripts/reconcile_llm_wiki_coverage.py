"""Resolve pending candidates already covered by reviewed LLM Wiki pages."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Optional

from app.core.config import Settings, get_settings
from app.services.knowledge_updates.llm_wiki_coverage_reconciliation import (
    LLMWikiCoverageReconciliationService,
)
from app.services.training.unified_repository import UnifiedFAQCandidateRepository

DEFAULT_REVIEWER = "scheduled-coverage-reconciliation"


def run_reconciliation(
    *,
    settings: Settings,
    db_path: Optional[str] = None,
    apply: bool = True,
    reviewer: str = DEFAULT_REVIEWER,
) -> dict[str, Any]:
    repository = UnifiedFAQCandidateRepository(
        db_path or os.path.join(settings.DATA_DIR, "unified_training.db")
    )
    report = LLMWikiCoverageReconciliationService(
        settings,
    ).reconcile_pending_repository(
        repository,
        apply=apply,
        reviewer=reviewer,
    )
    return report.to_response()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile pending training candidates already covered by reviewed "
            "LLM Wiki pages."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report covered candidates without mutating review state.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override unified training database path.",
    )
    parser.add_argument(
        "--reviewer",
        default=DEFAULT_REVIEWER,
        help="Reviewer marker written to auto-approved candidates.",
    )
    args = parser.parse_args()

    result = run_reconciliation(
        settings=get_settings(),
        db_path=args.db_path,
        apply=not args.dry_run,
        reviewer=args.reviewer,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Generate staff-only code evidence JSONL from a source checkout."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.rag.code_evidence_extractor import (  # noqa: E402
    CodeEvidenceExtractor,
    CodeEvidenceFreshnessChecker,
    write_code_evidence_jsonl,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    commit = args.commit or _git_commit(args.repo_path)
    extractor = CodeEvidenceExtractor(
        repo_path=args.repo_path,
        repo=args.repo,
        commit=commit,
        freshness_class=args.freshness_class,
    )
    records = extractor.extract()
    report = CodeEvidenceFreshnessChecker(args.repo_path).check(records)
    write_code_evidence_jsonl(records, args.output)

    summary = {
        "repo": args.repo,
        "commit": commit,
        "output": str(args.output),
        "records": len(records),
        "freshness": {
            "total": report.total,
            "valid": report.valid,
            "stale": report.stale,
            "failures": report.failures,
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if report.stale else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-path", type=Path, required=True)
    parser.add_argument("--repo", required=True, help="Repository slug, e.g. bisq2")
    parser.add_argument("--commit", help="Source commit hash. Defaults to git HEAD.")
    parser.add_argument(
        "--freshness-class",
        default="main_branch",
        choices=["main_branch", "release_bound", "generated"],
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("api/data/code_knowledge/code_evidence.jsonl"),
    )
    return parser.parse_args(argv)


def _git_commit(repo_path: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        raise SystemExit(
            "--commit is required when the source path is not a Git checkout"
        ) from exc
    return result.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())

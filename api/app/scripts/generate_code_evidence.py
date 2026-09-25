#!/usr/bin/env python3
"""Generate staff-only code evidence JSONL from a source checkout."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.rag.code_evidence import CodeEvidenceLoader  # noqa: E402
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
        release_tag=args.release_tag,
    )
    records = extractor.extract()
    if args.require_symbol:
        records = [record for record in records if record.symbol in args.require_symbol]
        missing = set(args.require_symbol) - {record.symbol for record in records}
        if missing:
            raise ValueError(
                "Required source coverage unavailable: " + ", ".join(sorted(missing))
            )
    report = CodeEvidenceFreshnessChecker(args.repo_path).check(records)
    if report.stale:
        raise ValueError("Source changed during extraction; evidence was not written")
    if args.merge_existing:
        if not args.release_tag:
            raise ValueError("Merging evidence requires an exact release tag")
        # Preserve all prior releases and other repositories. A same-tag commit
        # change is rejected rather than silently replacing the release identity.
        previous = CodeEvidenceLoader(args.merge_existing).load()
        if any(
            record.repo == args.repo
            and record.release_tag == args.release_tag
            and record.commit != commit
            for record in previous
        ):
            raise ValueError("Existing release tag is bound to a different commit")
        merged = {record.id: record for record in previous}
        merged.update({record.id: record for record in records})
        write_code_evidence_jsonl(merged.values(), args.output)
    else:
        write_code_evidence_jsonl(records, args.output)

    summary = {
        "repo": args.repo,
        "commit": commit,
        "release_tag": args.release_tag,
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
    parser.add_argument(
        "--commit", help="Full source commit hash. Must equal clean git HEAD."
    )
    parser.add_argument(
        "--release-tag",
        help="Local tag verified against the official release; must resolve to HEAD.",
    )
    parser.add_argument(
        "--freshness-class",
        default="main_branch",
        choices=["main_branch", "release_bound", "generated"],
    )
    parser.add_argument(
        "--require-symbol",
        action="append",
        default=[],
        help="Retain these exact symbols only; fail if any is absent. Repeatable coverage gate.",
    )
    parser.add_argument(
        "--merge-existing",
        type=Path,
        help="Merge the verified slice with this existing corpus, preserving other releases.",
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

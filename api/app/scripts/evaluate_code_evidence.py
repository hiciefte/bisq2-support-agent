#!/usr/bin/env python3
"""Evaluate staff-only code evidence retrieval against golden cases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.rag.code_evidence import (  # noqa: E402
    CodeEvidenceLoader,
    StaffCodeEvidenceRetriever,
)
from app.services.rag.code_evidence_evaluation import (  # noqa: E402
    CodeEvidenceRetrievalEvaluator,
    load_code_evidence_eval_cases,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cases = load_code_evidence_eval_cases(args.cases)
    retriever = StaffCodeEvidenceRetriever(CodeEvidenceLoader(args.evidence))
    result = CodeEvidenceRetrievalEvaluator(retriever).evaluate(cases, k=args.k)
    payload = result.to_dict()

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not result.failures else 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("api/data/code_knowledge/code_evidence.jsonl"),
    )
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--k", type=int, default=3)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())

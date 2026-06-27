"""Offline retrieval evaluation for staff-only code evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.services.rag.code_evidence import ALLOWED_PROTOCOLS


@dataclass(frozen=True)
class CodeEvidenceEvalCase:
    """One retrieval evaluation case for code evidence."""

    question: str
    expected_ids: list[str]
    protocol: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CodeEvidenceEvalCase":
        question = data.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Code evidence eval case requires non-empty question")

        expected_ids = data.get("expected_ids")
        if not isinstance(expected_ids, list) or not expected_ids:
            raise ValueError(
                "Code evidence eval case expected_ids must be a non-empty list"
            )

        normalized_expected_ids: list[str] = []
        for item in expected_ids:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    "Code evidence eval case expected_ids must contain non-empty strings"
                )
            normalized_expected_ids.append(item.strip())

        protocol_value = data.get("protocol")
        protocol: str | None = None
        if protocol_value is not None:
            if not isinstance(protocol_value, str) or not protocol_value.strip():
                raise ValueError(
                    "Code evidence eval case protocol must be a non-empty string"
                )
            protocol = protocol_value.strip()
            if protocol not in ALLOWED_PROTOCOLS:
                raise ValueError(
                    f"Unsupported code evidence eval protocol '{protocol}'"
                )

        return cls(
            question=question.strip(),
            expected_ids=normalized_expected_ids,
            protocol=protocol,
        )


@dataclass(frozen=True)
class CodeEvidenceRetrievalEvaluationResult:
    """Aggregate code evidence retrieval metrics."""

    total_cases: int
    recall_at_k: float
    mrr: float
    failures: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        return {
            "total_cases": self.total_cases,
            "recall_at_k": self.recall_at_k,
            "mrr": self.mrr,
            "failures": self.failures,
        }


class CodeEvidenceRetrievalEvaluator:
    """Measure code-evidence first-pass retrieval quality."""

    def __init__(self, retriever: Any) -> None:
        self.retriever = retriever

    def evaluate(
        self, cases: Iterable[CodeEvidenceEvalCase], *, k: int = 3
    ) -> CodeEvidenceRetrievalEvaluationResult:
        case_list = list(cases)
        failures: list[dict[str, object]] = []
        recall_values: list[float] = []
        reciprocal_ranks: list[float] = []

        for case in case_list:
            expected = list(dict.fromkeys(case.expected_ids))
            if not expected:
                failures.append(
                    {
                        "question": case.question,
                        "reason": "missing_expected_ids",
                    }
                )
                recall_values.append(0.0)
                reciprocal_ranks.append(0.0)
                continue

            docs = self.retriever.retrieve(
                case.question,
                protocol=case.protocol,
                k=k,
                min_score=0.0,
            )
            retrieved_ids = [
                str(getattr(doc, "id", None) or doc.metadata.get("id") or "")
                for doc in docs
            ]
            retrieved_set = set(retrieved_ids)
            expected_set = set(expected)
            found = expected_set & retrieved_set
            recall_values.append(len(found) / len(expected_set))
            reciprocal_ranks.append(_reciprocal_rank(retrieved_ids, expected_set))

            missing = [item for item in expected if item not in retrieved_set]
            if missing:
                failures.append(
                    {
                        "question": case.question,
                        "expected_ids": expected,
                        "retrieved_ids": retrieved_ids,
                        "missing_ids": missing,
                    }
                )

        total = len(case_list)
        return CodeEvidenceRetrievalEvaluationResult(
            total_cases=total,
            recall_at_k=_mean(recall_values),
            mrr=_mean(reciprocal_ranks),
            failures=failures,
        )


def load_code_evidence_eval_cases(path: str | Path) -> list[CodeEvidenceEvalCase]:
    """Load retrieval evaluation cases from JSON or JSONL."""
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        raw = json.loads(text)
        rows = raw.get("cases", raw) if isinstance(raw, dict) else raw

    if not isinstance(rows, list):
        raise ValueError("Code evidence evaluation cases must be a JSON list")
    return [
        CodeEvidenceEvalCase.from_dict(row) for row in rows if isinstance(row, dict)
    ]


def _reciprocal_rank(retrieved_ids: list[str], expected_ids: set[str]) -> float:
    for index, document_id in enumerate(retrieved_ids, start=1):
        if document_id in expected_ids:
            return 1 / index
    return 0.0


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)

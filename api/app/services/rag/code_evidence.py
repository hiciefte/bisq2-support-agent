"""Staff-only code evidence loading and lightweight retrieval."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.services.rag.interfaces import RetrievedDocument

CODE_EVIDENCE_TYPE = "code_fact"
STAFF_ONLY_AUDIENCE = "staff_only"
ALLOWED_AUDIENCES = {
    STAFF_ONLY_AUDIENCE,
    "public_review_candidate",
    "public_reviewed",
}
ALLOWED_FRESHNESS_CLASSES = {"release_bound", "main_branch", "generated"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high"}
ALLOWED_PROTOCOLS = {"bisq_easy", "multisig_v1", "musig", "all"}

_SECRET_TOKEN_RE = re.compile(
    r"\b(?:sk|pk|xox[baprs]|gh[pousr]|glpat|AKIA|xprv)[A-Za-z0-9_\-]{6,}\b"
)
_SENSITIVE_WORD_RE = re.compile(
    r"\b("
    r"password|passwd|secret|token|api[ _-]?key|private[ _-]?key|"
    r"mnemonic|seed[ _-]?phrase|wallet[ _-]?seed"
    r")\b",
    re.IGNORECASE,
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"\b(?P<key>"
    r"password|passwd|secret|token|api[ _-]?key|private[ _-]?key|"
    r"mnemonic|seed[ _-]?phrase|wallet[ _-]?seed"
    r")"
    r"(?P<middle>[^.?!\n]{0,80}?\b(?:is|=|:)\s*)"
    r"(?P<value>[A-Za-z0-9._/\-+=]{4,})",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[a-z0-9_]{3,}", re.IGNORECASE)


def _redact_sensitive_text(text: str) -> str:
    """Remove obvious secrets from generated code evidence text."""
    redacted = str(text or "")
    redacted = _SECRET_TOKEN_RE.sub("[REDACTED]", redacted)

    def _replace_assignment(match: re.Match[str]) -> str:
        return f"[REDACTED]{match.group('middle')}[REDACTED]"

    redacted = _SENSITIVE_ASSIGNMENT_RE.sub(_replace_assignment, redacted)
    redacted = _SENSITIVE_WORD_RE.sub("[REDACTED]", redacted)
    return re.sub(r"(?:\[REDACTED\]\s+){2,}", "[REDACTED] ", redacted)


def _require_string(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Code evidence field '{field}' must be a non-empty string")
    return value.strip()


def _require_int(data: dict[str, Any], field: str) -> int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Code evidence field '{field}' must be an integer")
    return value


def _require_string_list(data: dict[str, Any], field: str) -> list[str]:
    value = data.get(field)
    if not isinstance(value, list) or not value:
        raise ValueError(f"Code evidence field '{field}' must be a non-empty list")
    output: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"Code evidence field '{field}' must contain non-empty strings"
            )
        output.append(item.strip())
    return output


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item).strip()
        for item in value
        if isinstance(item, str) and str(item).strip()
    ]


@dataclass(frozen=True)
class CodeEvidenceRecord:
    """Structured code-derived support evidence.

    Records can describe staff-only implementation evidence or public review
    candidates, but the first retriever intentionally exposes only
    ``audience=staff_only`` records to staff-assist grounding.
    """

    id: str
    type: str
    repo: str
    commit: str
    path: str
    line_start: int
    line_end: int
    symbol: str
    protocol: str
    audience: str
    freshness_class: str
    risk_level: str
    claim: str
    support_use: str
    source_refs: list[str]
    public_guidance: str | None = None
    applies_to_versions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CodeEvidenceRecord":
        record_type = _require_string(data, "type")
        if record_type != CODE_EVIDENCE_TYPE:
            raise ValueError("Code evidence field 'type' must be 'code_fact'")

        protocol = _require_string(data, "protocol")
        if protocol not in ALLOWED_PROTOCOLS:
            raise ValueError(f"Unsupported code evidence protocol '{protocol}'")

        audience = _require_string(data, "audience")
        if audience not in ALLOWED_AUDIENCES:
            raise ValueError(f"Unsupported code evidence audience '{audience}'")

        freshness_class = _require_string(data, "freshness_class")
        if freshness_class not in ALLOWED_FRESHNESS_CLASSES:
            raise ValueError(
                f"Unsupported code evidence freshness_class '{freshness_class}'"
            )

        risk_level = _require_string(data, "risk_level")
        if risk_level not in ALLOWED_RISK_LEVELS:
            raise ValueError(f"Unsupported code evidence risk_level '{risk_level}'")

        line_start = _require_int(data, "line_start")
        line_end = _require_int(data, "line_end")
        if line_start <= 0 or line_end < line_start:
            raise ValueError("Code evidence line range must be positive and ordered")

        public_guidance = _optional_string(data.get("public_guidance"))
        if audience in {"public_review_candidate", "public_reviewed"}:
            if not public_guidance:
                raise ValueError(
                    "Public code evidence requires non-empty public_guidance"
                )

        return cls(
            id=_require_string(data, "id"),
            type=record_type,
            repo=_require_string(data, "repo"),
            commit=_require_string(data, "commit"),
            path=_require_string(data, "path"),
            line_start=line_start,
            line_end=line_end,
            symbol=_require_string(data, "symbol"),
            protocol=protocol,
            audience=audience,
            freshness_class=freshness_class,
            risk_level=risk_level,
            claim=_redact_sensitive_text(_require_string(data, "claim")),
            support_use=_redact_sensitive_text(_require_string(data, "support_use")),
            source_refs=_require_string_list(data, "source_refs"),
            public_guidance=(
                _redact_sensitive_text(public_guidance) if public_guidance else None
            ),
            applies_to_versions=_optional_string_list(
                data.get("applies_to_versions")
            ),
        )

    def to_retrieved_document(self, *, score: float = 0.0) -> RetrievedDocument:
        content = "\n".join(
            [
                f"Claim: {self.claim}",
                f"Support use: {self.support_use}",
                f"Freshness: {self.freshness_class}",
                f"Risk: {self.risk_level}",
            ]
        )
        return RetrievedDocument(
            id=self.id,
            content=content,
            metadata={
                "id": self.id,
                "type": self.type,
                "repo": self.repo,
                "commit": self.commit,
                "path": self.path,
                "line_start": self.line_start,
                "line_end": self.line_end,
                "symbol": self.symbol,
                "protocol": self.protocol,
                "audience": self.audience,
                "freshness_class": self.freshness_class,
                "risk_level": self.risk_level,
                "claim": self.claim,
                "support_use": self.support_use,
                "source_refs": list(self.source_refs),
                "public_guidance": self.public_guidance,
                "applies_to_versions": list(self.applies_to_versions),
            },
            score=score,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)


class CodeEvidenceLoader:
    """Load structured code evidence from a JSONL file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> list[CodeEvidenceRecord]:
        if not self.path.exists():
            return []

        records: list[CodeEvidenceRecord] = []
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError("record must be a JSON object")
                records.append(CodeEvidenceRecord.from_dict(raw))
            except Exception as exc:
                raise ValueError(
                    f"Invalid code evidence record at {self.path}:{line_number}: {exc}"
                ) from exc
        return records


class StaffCodeEvidenceRetriever:
    """Small staff-only retriever for the first code-knowledge slice."""

    def __init__(self, loader: CodeEvidenceLoader):
        self.loader = loader

    def retrieve(
        self,
        query: str,
        *,
        protocol: str | None = None,
        k: int = 3,
        min_score: float = 0.3,
    ) -> list[RetrievedDocument]:
        query_terms = set(_TOKEN_RE.findall(str(query or "").lower()))
        candidates = [
            record
            for record in self.loader.load()
            if record.audience == STAFF_ONLY_AUDIENCE
            and (protocol is None or record.protocol in {protocol, "all"})
        ]

        scored = [
            (record, self._score_record(record, query_terms)) for record in candidates
        ]
        scored = [(record, score) for record, score in scored if score >= min_score]
        scored.sort(key=lambda item: item[1], reverse=True)
        return [
            record.to_retrieved_document(score=score)
            for record, score in scored[: max(1, int(k))]
        ]

    def _score_record(
        self,
        record: CodeEvidenceRecord,
        query_terms: Iterable[str],
    ) -> float:
        haystack = " ".join(
            [
                record.claim,
                record.support_use,
                record.symbol,
                record.path,
                record.protocol,
            ]
        ).lower()
        terms = set(query_terms)
        if not terms:
            return 0.0
        matches = sum(1 for term in terms if term in haystack)
        return matches / len(terms)

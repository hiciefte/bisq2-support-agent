"""Staff-only code evidence loading and lightweight retrieval."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

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
_STOP_WORDS = set(
    "why can how what when where does did do the and for from with this that have has had are was were been into only not user users bisq already multiple meantime times running using updated version also should would could use support staff evidence".split()
)
_PRODUCT_REPOS = {"bisq1": "bisq", "bisq2": "bisq2"}


def canonical_code_repo(repo: str | None) -> str | None:
    return {
        "bisq": "bisq",
        "bisq1": "bisq",
        "bisq-network/bisq": "bisq",
        "bisq2": "bisq2",
        "bisq-network/bisq2": "bisq2",
    }.get(str(repo or "").lower())


def explicit_product(question: str) -> str | None:
    """Infer product from explicit user wording, never a retrieved document."""
    products = set()
    if re.search(r"\bbisq[ _-]?1\b|\bmultisig(?:[ _-]?v?1)?\b", question, re.I):
        products.add("bisq1")
    if re.search(r"\bbisq[ _-]?2\b|\bbisq[ _-]?easy\b|\bmusig\b", question, re.I):
        products.add("bisq2")
    return products.pop() if len(products) == 1 else None


def code_repo_for_context(
    product: str | None, protocol: str | None = None
) -> str | None:
    return _PRODUCT_REPOS.get(str(product)) or {
        "multisig_v1": "bisq",
        "bisq_easy": "bisq2",
        "musig": "bisq2",
    }.get(str(protocol))


_TOKEN_RE = re.compile(r"[a-z0-9_]{3,}", re.IGNORECASE)
# Bound user-supplied version components and prerelease labels before matching.
_VERSION_PATTERN = r"[0-9]{1,9}\.[0-9]{1,9}\.[0-9]{1,9}(?:-[A-Za-z0-9.-]{1,32})?"
_VERSION_RE = re.compile(rf"v?({_VERSION_PATTERN})")


def release_version(tag: str) -> str:
    """Accept an exact release identity, never a branch or a version range."""
    match = _VERSION_RE.fullmatch(tag)
    if match is not None:
        version = match.group(1)
        core, _, prerelease = version.partition("-")
        identifiers = core.split(".")
        if prerelease:
            identifiers.extend(prerelease.split("."))
        if all(
            identifier
            and not (
                identifier.isdigit()
                and len(identifier) > 1
                and identifier.startswith("0")
            )
            for identifier in identifiers
        ):
            return version
    raise ValueError("Release tag must identify an exact semantic version")


def explicit_user_version(question: str) -> str | None:
    """Read explicit version wording from the user, never retrieved evidence."""
    matches = re.findall(
        r"\b(?:bisq(?:\s+(?:1|2|easy))?\s*(?:version\s*|v)?|(?:version|running|using)\s+|v)"
        rf"({_VERSION_PATTERN})(?![\w+-]|\.[\w.-])\b",
        question,
        re.IGNORECASE,
    )
    try:
        versions = {release_version(match) for match in matches}
    except ValueError:
        return None
    return versions.pop() if len(versions) == 1 else None


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
    release_tag: str | None = None
    source_sha256: str | None = None
    match_terms: list[str] = field(default_factory=list)

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
        tag = _optional_string(data.get("release_tag"))
        source_sha256 = _optional_string(data.get("source_sha256"))
        versions = _optional_string_list(data.get("applies_to_versions"))
        if source_sha256 and not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
            raise ValueError("source_sha256 must be a full SHA256 digest")
        if freshness_class == "release_bound":
            if not tag or versions != [release_version(tag)]:
                raise ValueError(
                    "Release-bound evidence requires matching tag and version"
                )
            if not source_sha256 or not re.fullmatch(
                r"[0-9a-f]{40}", _require_string(data, "commit")
            ):
                raise ValueError("Release-bound evidence requires full source hashes")
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
            applies_to_versions=versions,
            release_tag=tag,
            source_sha256=source_sha256,
            match_terms=[
                _redact_sensitive_text(term)
                for term in _optional_string_list(data.get("match_terms"))
            ],
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
                "release_tag": self.release_tag,
                "source_sha256": self.source_sha256,
                "match_terms": list(self.match_terms),
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

    def retrieve_release_notes(
        self, query: str, **context: Any
    ) -> list[dict[str, Any]]:
        from app.services.rag.release_notes import ReleaseNotesLoader

        return ReleaseNotesLoader(
            self.loader.path.with_name("release_notes.jsonl")
        ).retrieve(query, **context)

    def retrieve(
        self,
        query: str,
        *,
        protocol: str | None = None,
        k: int = 3,
        min_score: float = 0.3,
        user_version: str | None = None,
        product: str | None = None,
    ) -> list[RetrievedDocument]:
        query = str(query or "")
        repo = code_repo_for_context(product or explicit_product(query), protocol)
        query_terms = set(_TOKEN_RE.findall(query.lower())) - _STOP_WORDS
        candidates = [
            record
            for record in self.loader.load()
            if record.audience == STAFF_ONLY_AUDIENCE
            and (repo is None or canonical_code_repo(record.repo) == repo)
            and (protocol in (None, "all") or record.protocol in {protocol, "all"})
            and (
                user_version is None
                or (
                    record.freshness_class == "release_bound"
                    and user_version.removeprefix("v") in record.applies_to_versions
                )
            )
        ]

        if user_version is None:
            latest: dict[str, str] = {}
            for record in candidates:
                if record.freshness_class == "release_bound" and record.release_tag:
                    identity = canonical_code_repo(record.repo) or record.repo
                    version = release_version(record.release_tag)
                    if "-" not in version and (
                        identity not in latest
                        or tuple(map(int, version.split(".")))
                        > tuple(map(int, latest[identity].split(".")))
                    ):
                        latest[identity] = version
            candidates = [
                record
                for record in candidates
                if not record.release_tag
                or (canonical_code_repo(record.repo) or record.repo) not in latest
                or release_version(record.release_tag)
                == latest[canonical_code_repo(record.repo) or record.repo]
            ]
        scored = [
            (record, self._score_record(record, query, query_terms))
            for record in candidates
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
        query: str,
        query_terms: set[str],
    ) -> float:
        # Exact errors and complete identifiers survive conversational filler;
        # lexical fallback uses whole tokens, never substring matches.
        lower = query.casefold()
        for term in record.match_terms:
            if re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", lower):
                return 1.0
        symbols = {
            symbol
            for symbol in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", record.symbol)
            if "_" in symbol or any(char.isupper() for char in symbol[1:])
        }
        if any(symbol.casefold() in query_terms for symbol in symbols):
            return 0.95
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
        matches = len(terms & set(_TOKEN_RE.findall(haystack)))
        return matches / len(terms)

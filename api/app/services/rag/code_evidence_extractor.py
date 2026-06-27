"""Deterministic code evidence extraction for staff-only grounding."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.services.rag.code_evidence import (
    CODE_EVIDENCE_TYPE,
    STAFF_ONLY_AUDIENCE,
    CodeEvidenceRecord,
)

_EXCLUDED_DIRS = {
    ".git",
    ".gradle",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "build",
    "data",
    "dist",
    "node_modules",
    "out",
    "target",
    "test",
    "tests",
    "tmp",
    "runtime_secrets",
    "venv",
    "wallets",
}
_JAVA_CONSTANT_RE = re.compile(
    r"\b(?:public|protected|private)?\s*"
    r"(?:(?:static|final)\s+){1,3}"
    r"[\w<>, ?\[\].]+\s+"
    r"(?P<name>[A-Z][A-Z0-9_]{2,})\s*=\s*(?P<value>[^;]+);"
)
_JAVA_TYPE_RE = re.compile(
    r"\b(?:class|interface|record|enum)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
)
_JAVA_ENUM_RE = re.compile(r"\benum\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\{")
_PATH_RE = re.compile(r'@Path\("(?P<path>[^"]*)"\)')
_HTTP_METHOD_RE = re.compile(r"@(GET|POST|PUT|DELETE|PATCH)\b")
_JAVA_METHOD_RE = re.compile(
    r"\b(?:public|protected|private)\s+"
    r"[\w<>, ?\[\].]+\s+"
    r"(?P<name>[a-zA-Z_][A-Za-z0-9_]*)\s*\("
)
_JAVA_THROW_RE = re.compile(
    r"\bthrow\s+new\s+(?P<exception>[A-Za-z_][A-Za-z0-9_]*Exception)\s*"
    r"\(\s*(?P<message>\"(?:\\.|[^\"])+\")"
)
_PY_HTTP_EXCEPTION_RE = re.compile(
    r"\bHTTPException\s*\((?P<args>[^)]*)\)", re.DOTALL
)
_PY_STATUS_CODE_RE = re.compile(r"\bstatus_code\s*=\s*(?P<status>\d{3})")
_PY_DETAIL_RE = re.compile(r"\bdetail\s*=\s*(?P<message>\"(?:\\.|[^\"])+\")")
_CONFIG_RE = re.compile(
    r"^(?P<key>[A-Za-z][A-Za-z0-9_.-]{2,})\s*(?:=|:)\s*(?P<value>.+)$"
)
_MARKDOWN_HEADING_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_.-]?key|private[_.-]?key|"
    r"mnemonic|seed[_.-]?phrase|wallet[_.-]?seed)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CodeEvidenceFreshnessReport:
    """Freshness check result for generated code evidence."""

    total: int
    valid: int
    stale: int
    failures: list[dict[str, object]]


class CodeEvidenceExtractor:
    """Extract conservative staff-only support facts from source files."""

    def __init__(
        self,
        *,
        repo_path: str | Path,
        repo: str,
        commit: str,
        audience: str = STAFF_ONLY_AUDIENCE,
        freshness_class: str = "main_branch",
    ) -> None:
        self.repo_path = Path(repo_path)
        self.repo = repo.strip()
        self.commit = commit.strip()
        self.audience = audience
        self.freshness_class = freshness_class

    def extract(self) -> list[CodeEvidenceRecord]:
        records: list[CodeEvidenceRecord] = []
        for path in sorted(self._iter_candidate_files()):
            relative_path = path.relative_to(self.repo_path).as_posix()
            text = path.read_text(encoding="utf-8", errors="ignore")
            lines = text.splitlines()
            suffix = path.suffix.lower()
            if suffix == ".java":
                records.extend(self._extract_java(relative_path, lines))
            elif suffix in {".conf", ".properties"}:
                records.extend(self._extract_config(relative_path, lines))
            elif suffix == ".py":
                records.extend(self._extract_python(relative_path, lines))
            elif suffix == ".md" and self._is_spec_markdown(relative_path):
                records.extend(self._extract_markdown_spec(relative_path, lines))

        unique: dict[str, CodeEvidenceRecord] = {}
        for record in records:
            unique.setdefault(record.id, record)
        return sorted(
            unique.values(),
            key=lambda item: (item.path, item.line_start, item.symbol),
        )

    def _iter_candidate_files(self) -> Iterable[Path]:
        for path in self.repo_path.rglob("*"):
            if not path.is_file():
                continue
            if any(part in _EXCLUDED_DIRS for part in path.parts):
                continue
            if path.suffix.lower() in {".java", ".py", ".conf", ".properties", ".md"}:
                yield path

    def _extract_java(
        self, relative_path: str, lines: list[str]
    ) -> list[CodeEvidenceRecord]:
        class_name = self._infer_java_type_name(relative_path, lines)
        records = []
        for line_index, line in enumerate(lines, start=1):
            match = _JAVA_CONSTANT_RE.search(line.strip())
            if match is None:
                continue
            name = match.group("name")
            value = self._clean_value(match.group("value"))
            symbol = f"{class_name}.{name}" if class_name else name
            records.append(
                self._record(
                    path=relative_path,
                    line_start=line_index,
                    line_end=line_index,
                    symbol=symbol,
                    claim=f"{symbol} defines {name} as {value}.",
                    support_use=(
                        "Use as staff evidence when checking implementation "
                        "constants, limits, or defaults."
                    ),
                )
            )

        records.extend(self._extract_java_enums(relative_path, lines))
        records.extend(self._extract_rest_endpoints(relative_path, lines))
        records.extend(self._extract_java_exceptions(relative_path, lines))
        return records

    def _extract_java_exceptions(
        self, relative_path: str, lines: list[str]
    ) -> list[CodeEvidenceRecord]:
        class_name = self._infer_java_type_name(relative_path, lines)
        records = []
        for line_index, line in enumerate(lines, start=1):
            match = _JAVA_THROW_RE.search(line.strip())
            if match is None:
                continue
            exception_name = match.group("exception")
            message = _decode_string_literal(match.group("message"))
            symbol = (
                f"{class_name}.{exception_name}" if class_name else exception_name
            )
            records.append(
                self._record(
                    path=relative_path,
                    line_start=line_index,
                    line_end=line_index,
                    symbol=symbol,
                    claim=(
                        f"{symbol} can emit exception message: "
                        f"{message}"
                    ),
                    support_use=(
                        "Use as staff evidence when matching a user-visible "
                        "exception message to a likely code path. Do not expose "
                        "raw exception classes or stack traces to customers."
                    ),
                    risk_level="high",
                )
            )
        return records

    def _extract_java_enums(
        self, relative_path: str, lines: list[str]
    ) -> list[CodeEvidenceRecord]:
        records = []
        for index, line in enumerate(lines):
            match = _JAVA_ENUM_RE.search(line)
            if match is None:
                continue

            enum_name = match.group("name")
            values: list[str] = []
            end_index = index
            for body_index in range(index + 1, len(lines)):
                end_index = body_index
                body_line = lines[body_index].strip()
                if not body_line or body_line.startswith("//"):
                    continue
                for raw_value in body_line.split(","):
                    value = raw_value.strip().rstrip(";{}")
                    value = re.sub(r"\(.*", "", value).strip()
                    if re.fullmatch(r"[A-Z][A-Z0-9_]*", value):
                        values.append(value)
                if ";" in body_line or "}" in body_line:
                    break

            if not values:
                continue
            records.append(
                self._record(
                    path=relative_path,
                    line_start=index + 1,
                    line_end=end_index + 1,
                    symbol=enum_name,
                    claim=f"{enum_name} defines enum states: {', '.join(values)}.",
                    support_use=(
                        "Use as staff evidence when checking state-machine "
                        "or workflow terminology."
                    ),
                )
            )
        return records

    def _extract_rest_endpoints(
        self, relative_path: str, lines: list[str]
    ) -> list[CodeEvidenceRecord]:
        records = []
        class_name = self._infer_java_type_name(relative_path, lines)
        class_path = ""
        pre_class_path: str | None = None
        pending_path: str | None = None
        pending_method: str | None = None
        annotation_start: int | None = None

        for index, line in enumerate(lines, start=1):
            path_match = _PATH_RE.search(line)
            if path_match is not None:
                if class_name and class_path:
                    pending_path = path_match.group("path")
                    annotation_start = annotation_start or index
                else:
                    pre_class_path = path_match.group("path")
                continue

            type_match = _JAVA_TYPE_RE.search(line)
            if type_match is not None and pre_class_path is not None:
                class_path = pre_class_path
                pre_class_path = None

            method_match = _HTTP_METHOD_RE.search(line)
            if method_match is not None:
                pending_method = method_match.group(1)
                annotation_start = annotation_start or index
                continue

            java_method = _JAVA_METHOD_RE.search(line)
            if java_method is None or pending_method is None:
                continue

            method_name = java_method.group("name")
            endpoint = _join_url_paths(class_path, pending_path or "")
            symbol = f"{class_name}.{method_name}" if class_name else method_name
            records.append(
                self._record(
                    path=relative_path,
                    line_start=annotation_start or index,
                    line_end=index,
                    symbol=symbol,
                    claim=(
                        f"{symbol} handles REST endpoint "
                        f"{pending_method} {endpoint or '/'}."
                    ),
                    support_use=(
                        "Use as staff evidence when checking API endpoint "
                        "behavior, routing, or permissions."
                    ),
                    risk_level="high",
                )
            )
            pending_path = None
            pending_method = None
            annotation_start = None
        return records

    def _extract_config(
        self, relative_path: str, lines: list[str]
    ) -> list[CodeEvidenceRecord]:
        records = []
        for line_index, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "//")):
                continue
            match = _CONFIG_RE.match(stripped)
            if match is None:
                continue
            key = match.group("key").strip()
            value = self._clean_value(match.group("value"))
            if _is_sensitive_text(key) or _is_sensitive_text(value):
                continue
            records.append(
                self._record(
                    path=relative_path,
                    line_start=line_index,
                    line_end=line_index,
                    symbol=key,
                    claim=f"Config default {key} is set to {value}.",
                    support_use=(
                        "Use as staff evidence when checking runtime defaults "
                        "or deployment-sensitive behavior."
                    ),
                    risk_level="medium",
                )
            )
        return records

    def _extract_python(
        self, relative_path: str, lines: list[str]
    ) -> list[CodeEvidenceRecord]:
        records = []
        for line_index, line in enumerate(lines, start=1):
            match = _PY_HTTP_EXCEPTION_RE.search(line.strip())
            if match is None:
                continue
            args = match.group("args")
            detail = _PY_DETAIL_RE.search(args)
            if detail is None:
                continue
            status_match = _PY_STATUS_CODE_RE.search(args)
            status = status_match.group("status") if status_match else "unknown"
            message = _decode_string_literal(detail.group("message"))
            symbol = f"HTTPException.{status}"
            records.append(
                self._record(
                    path=relative_path,
                    line_start=line_index,
                    line_end=line_index,
                    symbol=symbol,
                    claim=(
                        f"{symbol} can return user-visible API error detail: "
                        f"{message}"
                    ),
                    support_use=(
                        "Use as staff evidence when matching an API error detail "
                        "to a likely support-agent route. Do not expose internal "
                        "route or traceback details to customers."
                    ),
                    risk_level="high",
                )
            )
        return records

    def _extract_markdown_spec(
        self, relative_path: str, lines: list[str]
    ) -> list[CodeEvidenceRecord]:
        records = []
        for index, line in enumerate(lines):
            match = _MARKDOWN_HEADING_RE.match(line.strip())
            if match is None:
                continue
            title = match.group("title").strip()
            paragraph, paragraph_line = _next_markdown_paragraph(lines, index + 1)
            if not paragraph:
                continue
            symbol = f"specification:{title}"
            records.append(
                self._record(
                    path=relative_path,
                    line_start=index + 1,
                    line_end=paragraph_line,
                    symbol=symbol,
                    claim=f"Specification section '{title}' states: {paragraph}",
                    support_use=(
                        "Use as staff evidence when checking protocol "
                        "specification wording."
                    ),
                    freshness_class="generated",
                    risk_level="low",
                )
            )
        return records

    def _record(
        self,
        *,
        path: str,
        line_start: int,
        line_end: int,
        symbol: str,
        claim: str,
        support_use: str,
        freshness_class: str | None = None,
        risk_level: str = "medium",
    ) -> CodeEvidenceRecord:
        source_ref = f"code:{self.repo}@{self.commit}:{path}:{line_start}-{line_end}"
        data = {
            "id": self._record_id(symbol, line_start),
            "type": CODE_EVIDENCE_TYPE,
            "repo": self.repo,
            "commit": self.commit,
            "path": path,
            "line_start": line_start,
            "line_end": line_end,
            "symbol": symbol,
            "protocol": _infer_protocol(path),
            "audience": self.audience,
            "freshness_class": freshness_class or self.freshness_class,
            "risk_level": risk_level,
            "claim": claim,
            "support_use": support_use,
            "source_refs": [source_ref],
        }
        return CodeEvidenceRecord.from_dict(data)

    def _record_id(self, symbol: str, line_start: int) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", symbol).strip("-")
        return f"{self.repo}:{self.commit[:12]}:{slug}:{line_start}"

    def _infer_java_type_name(self, relative_path: str, lines: list[str]) -> str:
        for line in lines[:80]:
            match = _JAVA_TYPE_RE.search(line)
            if match is not None:
                return match.group("name")
        return Path(relative_path).stem

    def _clean_value(self, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value.strip().strip("\"'"))
        return cleaned[:120]

    def _is_spec_markdown(self, relative_path: str) -> bool:
        normalized = relative_path.lower()
        return "specification" in normalized or "/spec" in normalized


class CodeEvidenceFreshnessChecker:
    """Check whether code evidence still points at existing source lines."""

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path)

    def check(
        self, records: Iterable[CodeEvidenceRecord]
    ) -> CodeEvidenceFreshnessReport:
        failures: list[dict[str, object]] = []
        total = 0
        valid = 0

        for record in records:
            total += 1
            failure = self._failure_for(record)
            if failure is None:
                valid += 1
            else:
                failures.append(failure)

        return CodeEvidenceFreshnessReport(
            total=total,
            valid=valid,
            stale=len(failures),
            failures=failures,
        )

    def _failure_for(self, record: CodeEvidenceRecord) -> dict[str, object] | None:
        source_path = self.repo_path / record.path
        if not source_path.exists():
            return {
                "id": record.id,
                "path": record.path,
                "reason": "missing_file",
            }

        line_count = len(
            source_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        )
        if (
            record.line_start <= 0
            or record.line_end < record.line_start
            or record.line_end > line_count
        ):
            return {
                "id": record.id,
                "path": record.path,
                "line_start": record.line_start,
                "line_end": record.line_end,
                "line_count": line_count,
                "reason": "line_range_out_of_bounds",
            }

        expected_ref = (
            f"code:{record.repo}@{record.commit}:"
            f"{record.path}:{record.line_start}-{record.line_end}"
        )
        if expected_ref not in record.source_refs:
            return {
                "id": record.id,
                "path": record.path,
                "reason": "source_ref_mismatch",
            }
        return None


def write_code_evidence_jsonl(
    records: Iterable[CodeEvidenceRecord], path: str | Path
) -> None:
    """Write records as sorted JSONL for reviewable diffs."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_records = sorted(
        records,
        key=lambda item: (item.repo, item.path, item.line_start, item.symbol),
    )
    rows = [
        json.dumps(record.to_dict(), sort_keys=True, ensure_ascii=False)
        for record in sorted_records
    ]
    output_path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")


def _infer_protocol(relative_path: str) -> str:
    normalized = relative_path.lower().replace("-", "_")
    if "bisq_easy" in normalized:
        return "bisq_easy"
    if "mu_sig" in normalized or "musig" in normalized:
        return "musig"
    if "multisig" in normalized or "bisq1" in normalized:
        return "multisig_v1"
    return "all"


def _join_url_paths(base: str, child: str) -> str:
    parts = [part.strip("/") for part in [base, child] if part and part.strip("/")]
    return "/" + "/".join(parts) if parts else "/"


def _next_markdown_paragraph(
    lines: list[str], start_index: int
) -> tuple[str | None, int]:
    for index in range(start_index, len(lines)):
        stripped = lines[index].strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return None, index + 1
        return stripped[:240], index + 1
    return None, len(lines)


def _is_sensitive_text(text: str) -> bool:
    return _SENSITIVE_KEY_RE.search(text) is not None


def _decode_string_literal(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] == '"':
        stripped = stripped[1:-1]
    return bytes(stripped, "utf-8").decode("unicode_escape")

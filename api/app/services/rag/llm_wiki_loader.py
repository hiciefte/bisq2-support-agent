"""Internal LLM Wiki loader for RAG indexing.

The internal LLM Wiki is the compiled support-intelligence layer. Raw support
conversations, FAQs, and external wiki pages remain evidence; only reviewed or
active LLM Wiki pages with explicit source references become RAG documents.
"""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml  # type: ignore[import-untyped]
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

LLM_WIKI_TYPE = "llm_wiki"
DEFAULT_PAGE_TYPE = "support_playbook"
REVIEWED_STATUS = "reviewed"
ACTIVE_STATUS = "active"
INDEXABLE_STATUSES = {REVIEWED_STATUS, ACTIVE_STATUS}
ALLOWED_STATUSES = {"draft", "proposed", REVIEWED_STATUS, ACTIVE_STATUS, "deprecated"}
ALLOWED_PROTOCOLS = {"all", "bisq_easy", "multisig_v1"}
ALLOWED_PAGE_TYPES = {
    "support_playbook",
    "concept",
    "procedure",
    "known_issue",
    "contradiction_note",
    "eval_note",
}
DEFAULT_LLM_WIKI_WEIGHT = 1.25


@dataclass(frozen=True)
class LLMWikiPage:
    """Validated internal LLM Wiki page ready for optional RAG conversion."""

    id: str
    title: str
    page_type: str
    status: str
    protocol: str
    source_refs: List[str]
    body: str
    path: Path
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    risk_level: Optional[str] = None

    def to_document(self, source_weight: float) -> Document:
        source_refs = "\n".join(f"- {ref}" for ref in self.source_refs)
        title_prefix = (
            "Support Playbook"
            if self.page_type == DEFAULT_PAGE_TYPE
            else "Internal LLM Wiki"
        )
        page_content = (
            f"{title_prefix}: {self.title}\n\n"
            f"{self.body.strip()}\n\n"
            f"Source refs:\n{source_refs}"
        )
        metadata: Dict[str, Any] = {
            "source": str(self.path),
            "title": self.title,
            "type": LLM_WIKI_TYPE,
            "page_type": self.page_type,
            "category": self.page_type,
            "source_weight": source_weight,
            "protocol": self.protocol,
            "status": self.status,
            "id": self.id,
            "source_refs": self.source_refs,
            "section": f"Internal LLM Wiki: {self.page_type.replace('_', ' ')}",
        }
        if self.reviewed_by:
            metadata["reviewed_by"] = self.reviewed_by
        if self.reviewed_at:
            metadata["reviewed_at"] = self.reviewed_at
        if self.risk_level:
            metadata["risk_level"] = self.risk_level
        return Document(page_content=page_content, metadata=metadata)


class LLMWikiLoader:
    """Load reviewed/active internal LLM Wiki pages from markdown."""

    def __init__(self, source_weights: Optional[Dict[str, float]] = None):
        self.source_weights = {
            LLM_WIKI_TYPE: DEFAULT_LLM_WIKI_WEIGHT,
            **(source_weights or {}),
        }

    def update_source_weights(self, new_weights: Dict[str, float]) -> None:
        """Update LLM Wiki source weighting without coupling to other loaders."""
        if LLM_WIKI_TYPE in new_weights:
            self.source_weights[LLM_WIKI_TYPE] = new_weights[LLM_WIKI_TYPE]
            logger.info(
                "Updated LLM Wiki source weight to %s",
                self.source_weights[LLM_WIKI_TYPE],
            )

    def load_documents(self, llm_wiki_dir: str | Path) -> List[Document]:
        """Load reviewed/active LLM Wiki markdown pages from a directory."""
        root = Path(llm_wiki_dir)
        if not root.exists():
            logger.info("LLM Wiki directory not found: %s", root)
            return []
        if not root.is_dir():
            logger.warning("LLM Wiki path is not a directory: %s", root)
            return []

        documents: List[Document] = []
        seen_ids: Set[str] = set()
        for path in sorted(root.rglob("*.md")):
            page = self._load_page(path)
            if page is None:
                continue
            if page.id in seen_ids:
                raise ValueError(f"duplicate LLM Wiki page id: {page.id}")
            seen_ids.add(page.id)
            if page.status not in INDEXABLE_STATUSES:
                logger.debug("Skipping non-indexable LLM Wiki page: %s", path)
                continue
            documents.append(
                page.to_document(
                    source_weight=self.source_weights.get(
                        LLM_WIKI_TYPE, DEFAULT_LLM_WIKI_WEIGHT
                    )
                )
            )

        logger.info("Loaded %d indexable LLM Wiki pages", len(documents))
        return documents

    def _load_page(self, path: Path) -> Optional[LLMWikiPage]:
        try:
            frontmatter, body = _split_frontmatter(path.read_text(encoding="utf-8"))
            page = _validate_page(frontmatter=frontmatter, body=body, path=path)
            return page
        except ValueError as exc:
            logger.warning("Skipping invalid LLM Wiki page %s: %s", path, exc)
            return None
        except Exception as exc:
            logger.error("Failed to load LLM Wiki page %s: %s", path, exc)
            return None


def _split_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    normalized = (text or "").lstrip("\ufeff")
    if not normalized.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")

    _, remainder = normalized.split("---\n", 1)
    if "\n---\n" not in remainder:
        raise ValueError("unterminated YAML frontmatter")

    raw_frontmatter, body = remainder.split("\n---\n", 1)
    parsed = yaml.safe_load(raw_frontmatter) or {}
    if not isinstance(parsed, dict):
        raise ValueError("frontmatter must be a mapping")
    return parsed, body.strip()


def _validate_page(
    *, frontmatter: Dict[str, Any], body: str, path: Path
) -> LLMWikiPage:
    page_id = _required_string(frontmatter, "id")
    page_source_type = _required_string(frontmatter, "type")
    status = _required_string(frontmatter, "status")
    protocol = _required_string(frontmatter, "protocol")
    title = _optional_string(frontmatter.get("title")) or page_id
    page_type = _optional_string(frontmatter.get("page_type")) or DEFAULT_PAGE_TYPE
    source_refs = _string_list(frontmatter.get("source_refs"))

    if page_source_type != LLM_WIKI_TYPE:
        raise ValueError(f"unsupported type: {page_source_type}")
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"unsupported status: {status}")
    if protocol not in ALLOWED_PROTOCOLS:
        raise ValueError(f"unsupported protocol: {protocol}")
    if page_type not in ALLOWED_PAGE_TYPES:
        raise ValueError(f"unsupported page_type: {page_type}")
    if status in INDEXABLE_STATUSES and not source_refs:
        raise ValueError("reviewed/active LLM Wiki pages require source_refs")
    if status in INDEXABLE_STATUSES and not body.strip():
        raise ValueError("reviewed/active LLM Wiki pages require body content")
    reviewed_at = _optional_string(frontmatter.get("reviewed_at"))
    if reviewed_at:
        try:
            datetime.fromisoformat(reviewed_at)
        except ValueError as exc:
            raise ValueError("reviewed_at must be ISO-8601 compatible") from exc

    return LLMWikiPage(
        id=page_id,
        title=title,
        page_type=page_type,
        status=status,
        protocol=protocol,
        source_refs=source_refs,
        body=body,
        path=path,
        reviewed_by=_optional_string(frontmatter.get("reviewed_by")),
        reviewed_at=reviewed_at,
        risk_level=_optional_string(frontmatter.get("risk_level")),
    )


def _required_string(frontmatter: Dict[str, Any], key: str) -> str:
    value = _optional_string(frontmatter.get(key))
    if not value:
        raise ValueError(f"missing required field: {key}")
    return value


def _optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Mapping):
        return []
    if not isinstance(value, Iterable):
        return []
    result = []
    for item in value:
        normalized = _optional_string(item)
        if normalized:
            result.append(normalized)
    return result

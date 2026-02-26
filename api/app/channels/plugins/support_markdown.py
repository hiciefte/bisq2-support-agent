"""Shared markdown rendering helpers for support-agent channel plugins."""

from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from app.channels.models import DocumentReference

BISQ2_FAQ_ONION_BASE_URL = (
    "http://bisq2ai4h4idzrwlnjjsj7vrbve4ufsxwagxermcch6v4odjdjblqlyd.onion"
)
_FOOTER_MARKERS = (
    "**Confidence:**",
    "**Sources:**",
    "**Answer quality**",
    "**Sources**",
)
_MAX_SOURCE_URL_LENGTH = 2048
_MAX_SOURCE_TITLE_LENGTH = 180

try:
    from markdown_it import MarkdownIt

    _MATRIX_MD = MarkdownIt("commonmark", {"html": False})
except Exception:  # pragma: no cover - optional dependency fallback
    _MATRIX_MD = None


@dataclass(frozen=True)
class _RenderedSource:
    source_type: str
    title: str
    url: Optional[str]


def compose_support_answer_markdown(
    answer_text: str,
    sources: Iterable[DocumentReference] | None,
    confidence_score: Optional[float],
) -> str:
    """Append deterministic confidence/sources markdown to a support answer.

    The renderer is idempotent: if the answer already contains confidence/sources
    footer markers, the original answer is returned unchanged.
    """
    base_answer = (answer_text or "").strip()
    if not base_answer:
        return ""
    if _has_footer_markers(base_answer):
        return base_answer

    source_entries = _build_source_entries(sources)
    confidence_value = _render_confidence_value(confidence_score)
    source_mix = _render_source_mix(source_entries)

    footer_lines: list[str] = []
    if confidence_value or source_mix:
        footer_lines.append("---")
        footer_lines.append("")
        footer_lines.append("**Answer quality**")
        if confidence_value:
            footer_lines.append(f"- Confidence: **{confidence_value}**")
        if source_mix:
            footer_lines.append(f"- Source mix: **{source_mix}**")

    if source_entries:
        if footer_lines:
            footer_lines.append("")
        footer_lines.append("**Sources**")
        footer_lines.extend(_render_source_lines(source_entries))

    if not footer_lines:
        return base_answer
    return f"{base_answer}\n\n" + "\n".join(footer_lines)


def serialize_sources_for_tracking(
    sources: Iterable[DocumentReference] | None,
) -> list[dict[str, Any]]:
    """Serialize source references into tracker-friendly dictionaries."""
    serialized: list[dict[str, Any]] = []
    for source in sources or []:
        serialized.append(
            {
                "document_id": _normalize_text(getattr(source, "document_id", None)),
                "title": _normalize_text(getattr(source, "title", None)),
                "url": _normalize_text(getattr(source, "url", None)),
                "section": _normalize_text(getattr(source, "section", None)),
                "category": _normalize_text(getattr(source, "category", None)),
                "protocol": _normalize_text(getattr(source, "protocol", None)),
                "relevance_score": getattr(source, "relevance_score", None),
            }
        )
    return serialized


def render_markdown_for_matrix(markdown_text: str) -> str:
    """Render markdown into safe Matrix-compatible HTML."""
    source = (markdown_text or "").strip()
    if not source:
        return ""

    if _MATRIX_MD is not None:
        # Escape raw HTML before markdown render to prevent HTML injection.
        escaped_source = html.escape(source)
        rendered = _MATRIX_MD.render(escaped_source).strip()
        # Strip dangerous URL schemes in generated links.
        rendered = re.sub(
            r'href="(?:javascript|data):[^"]*"',
            'href="#"',
            rendered,
            flags=re.IGNORECASE,
        )
        return rendered

    # Minimal fallback renderer for environments without markdown-it-py.
    escaped = html.escape(source)
    escaped = re.sub(
        r"\[(.+?)\]\((https?://[^)]+)\)",
        r'<a href="\2">\1</a>',
        escaped,
    )
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = escaped.replace("\n", "<br>")
    return escaped


def render_plain_text_from_markdown(markdown_text: str) -> str:
    """Render markdown into a plain-text fallback for Matrix ``body``."""
    text = (markdown_text or "").strip()
    if not text:
        return ""

    # Convert links/images to readable labels.
    text = re.sub(r"!\[([^\]]*)\]\((?:[^)]+)\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\((?:[^)]+)\)", r"\1", text)

    # Remove markdown block markers.
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = re.sub(r"(?m)^\s*[-*_]{3,}\s*$", "", text)

    # Remove inline markdown emphasis/code markers.
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"_(.*?)_", r"\1", text)

    # Unescape common markdown escape sequences so editors don't show slashes.
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!~])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return _strip_dangerous_chars(text) or ""


def build_matrix_message_content(markdown_text: str) -> dict[str, Any]:
    """Build Matrix payload with plain-text fallback plus rich HTML body."""
    source = (markdown_text or "").strip()
    if not source:
        return {"msgtype": "m.text", "body": ""}

    plain_body = render_plain_text_from_markdown(source) or source
    html_body = render_markdown_for_matrix(source)
    content: dict[str, Any] = {
        "msgtype": "m.text",
        "body": plain_body,
    }
    if html_body:
        content["format"] = "org.matrix.custom.html"
        content["formatted_body"] = html_body
    return content


def _has_footer_markers(text: str) -> bool:
    return any(marker in text for marker in _FOOTER_MARKERS)


def _render_confidence_value(confidence_score: Optional[float]) -> Optional[str]:
    if confidence_score is None:
        return None
    try:
        bounded_score = max(0.0, min(1.0, float(confidence_score)))
    except (TypeError, ValueError):
        return None

    percent = int(round(bounded_score * 100))
    return f"{_resolve_confidence_label(bounded_score)} ({percent}%)"


def _resolve_confidence_label(score: float) -> str:
    if score >= 0.85:
        return "Verified"
    if score >= 0.70:
        return "Likely accurate"
    if score >= 0.50:
        return "Needs verification"
    return "Community response"


def _build_source_entries(
    sources: Iterable[DocumentReference] | None,
) -> list[_RenderedSource]:
    entries: list[_RenderedSource] = []
    for index, source in enumerate(sources or [], start=1):
        entries.append(
            _RenderedSource(
                source_type=_resolve_source_type(source),
                title=_resolve_source_title(source, index),
                url=_resolve_source_url(source),
            )
        )
    return entries


def _render_source_mix(entries: list[_RenderedSource]) -> Optional[str]:
    if not entries:
        return None

    counts = Counter(entry.source_type for entry in entries)
    ordered_types = ("FAQ", "Wiki", "Doc")
    parts: list[str] = []
    for source_type in ordered_types:
        count = counts.get(source_type, 0)
        if count:
            parts.append(_render_source_mix_part(source_type, count))
    return ", ".join(parts) if parts else None


def _render_source_mix_part(source_type: str, count: int) -> str:
    if source_type == "FAQ":
        label = "FAQ" if count == 1 else "FAQs"
        return f"{count} {label}"
    if source_type == "Wiki":
        label = "Wiki page" if count == 1 else "Wiki pages"
        return f"{count} {label}"
    label = "Doc" if count == 1 else "Docs"
    return f"{count} {label}"


def _render_source_lines(entries: list[_RenderedSource]) -> list[str]:
    rows: list[str] = []
    for entry in entries:
        icon = _source_icon_markdown(entry.source_type)
        source_type = _escape_markdown_inline(entry.source_type)
        title = _escape_markdown_inline(entry.title)
        if entry.url:
            rows.append(f"- {icon} [{source_type}] [{title}]({entry.url})")
        else:
            rows.append(f"- {icon} [{source_type}] {title}")
    return rows


def _source_icon_markdown(source_type: str) -> str:
    if source_type == "FAQ":
        return "![FAQ](bisq-icon://faq)"
    if source_type == "Wiki":
        return "![Wiki](bisq-icon://wiki)"
    return "![Doc](bisq-icon://wiki)"


def _resolve_source_type(source: DocumentReference) -> str:
    if _is_faq_source(source):
        return "FAQ"
    if _is_wiki_source(source):
        return "Wiki"
    return "Doc"


def _resolve_source_title(source: DocumentReference, index: int) -> str:
    title = _normalize_text(getattr(source, "title", None))
    if title:
        return _truncate_source_title(title)
    document_id = _normalize_text(getattr(source, "document_id", None))
    if document_id:
        return _truncate_source_title(document_id)
    return f"Source {index}"


def _resolve_source_url(source: DocumentReference) -> Optional[str]:
    raw_url = _normalize_text(getattr(source, "url", None))
    if raw_url:
        faq_slug = _extract_faq_slug(raw_url)
        if faq_slug:
            return _sanitize_outbound_url(f"{BISQ2_FAQ_ONION_BASE_URL}/faq/{faq_slug}")
        return _sanitize_outbound_url(raw_url)

    if not _is_faq_source(source):
        return None

    faq_slug = _extract_slug_from_source_metadata(source)
    if not faq_slug:
        return None
    return _sanitize_outbound_url(f"{BISQ2_FAQ_ONION_BASE_URL}/faq/{faq_slug}")


def _extract_faq_slug(raw_url: str) -> Optional[str]:
    parsed = urlparse(raw_url)
    path = parsed.path or raw_url
    candidate = None

    match = re.search(r"/(?:faq|faqs)/([^/?#]+)", path, flags=re.IGNORECASE)
    if match:
        candidate = match.group(1)

    if candidate is None and path.lower().startswith("/faq/"):
        candidate = path[5:].strip("/")
    if candidate is None and path.lower().startswith("faq/"):
        candidate = path[4:].strip("/")

    return _normalize_slug(candidate)


def _extract_slug_from_source_metadata(source: DocumentReference) -> Optional[str]:
    document_id = _normalize_text(getattr(source, "document_id", None))
    if document_id:
        slug = _normalize_slug(document_id)
        if slug and not _looks_like_uuid(slug):
            return slug

    title = _normalize_text(getattr(source, "title", None))
    return _normalize_slug(title)


def _is_faq_source(source: DocumentReference) -> bool:
    category = _normalize_text(getattr(source, "category", None))
    if category and "faq" in category.lower():
        return True

    raw_url = _normalize_text(getattr(source, "url", None))
    if not raw_url:
        return False
    lowered = raw_url.lower()
    return "/faq/" in lowered or "/faqs/" in lowered


def _is_wiki_source(source: DocumentReference) -> bool:
    category = _normalize_text(getattr(source, "category", None))
    if category and "wiki" in category.lower():
        return True

    raw_url = _normalize_text(getattr(source, "url", None))
    if not raw_url:
        return False

    lowered = raw_url.lower()
    if "bisq.wiki" in lowered:
        return True

    parsed = urlparse(raw_url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    return "wiki" in host or path.startswith("/wiki/")


def _normalize_slug(value: Optional[str]) -> Optional[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return None

    slug = normalized.lower()
    slug = re.sub(r"^https?://[^/]+/", "", slug)
    slug = re.sub(r"^faqs?/", "", slug)
    slug = slug.strip("/")
    slug = re.sub(r"[^a-z0-9-]", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or None


def _normalize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _looks_like_uuid(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value
        )
    )


def _sanitize_outbound_url(raw_url: Optional[str]) -> Optional[str]:
    value = _strip_dangerous_chars(_normalize_text(raw_url))
    if not value:
        return None
    if len(value) > _MAX_SOURCE_URL_LENGTH:
        return None
    try:
        parsed = urlparse(value)
    except Exception:
        return None
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None
    return value


def _escape_markdown_inline(value: str) -> str:
    sanitized = _strip_dangerous_chars(value) or ""
    escaped = sanitized.replace("\\", "\\\\")
    for ch in ("[", "]", "(", ")", "*", "_", "~", "`", "!"):
        escaped = escaped.replace(ch, f"\\{ch}")
    return escaped


def _truncate_source_title(value: str) -> str:
    if len(value) <= _MAX_SOURCE_TITLE_LENGTH:
        return value
    return value[: _MAX_SOURCE_TITLE_LENGTH - 1].rstrip() + "…"


def _strip_dangerous_chars(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    filtered = "".join(
        ch
        for ch in value
        if ord(ch) >= 0x20 and ord(ch) != 0x7F and not _is_bidi_control(ch)
    )
    normalized = " ".join(filtered.strip().split())
    return normalized or None


def _is_bidi_control(ch: str) -> bool:
    return ch in {
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
    }

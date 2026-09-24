"""Resolve existing knowledge and bounded live tools for internal staff notes.

Retrieval metadata is a hint, not publication authority. FAQ bodies are re-read
from the authoritative service. Compiled guidance retains its own provenance;
page-level references never become invented claim-level public citations.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlsplit

from app.channels.staff_assist.public_context import (
    ContextEvidence,
    PublicEvidence,
    StaffEvidence,
)
from app.services.faq.slug_manager import SlugManager
from app.services.rag.source_refs import is_precise_code_source_ref


@dataclass
class EvidenceBundle:
    evidence: list[ContextEvidence] = field(default_factory=list)
    internal_grounding: dict[str, Any] | None = None
    diagnostics: list[str] = field(default_factory=list)


def _value(row: Any, key: str, default: Any = None) -> Any:
    return (
        row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)
    )


def _identifier(kind: str, value: str) -> str:
    return kind + "-" + hashlib.sha256(value.encode()).hexdigest()[:20]


def _private(metadata: dict[str, Any]) -> bool:
    return metadata.get("private") is True or metadata.get("audience") == "private"


def _valid_ref(ref: Any) -> bool:
    if not isinstance(ref, str) or not ref or len(ref) > 1000:
        return False
    if any(ord(char) < 32 for char in ref):
        return False
    if ref.startswith("code:"):
        return is_precise_code_source_ref(ref)
    if ref.startswith(("faq:", "llm_wiki:")):
        return bool(re.fullmatch(r"(?:faq|llm_wiki):[A-Za-z0-9_.-]+", ref))
    if ref.startswith("wiki:"):
        return bool(ref[5:].strip()) and not any(char in ref for char in "<>\\")
    # Internal provenance is not a public citation allowlist. Reviewed pages
    # legitimately cite upstream Bitcoin, Tor, OS and payment documentation.
    # Preserve those refs without fetching them or rendering them as public links.
    try:
        parsed = urlsplit(ref)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and not any(char.isspace() or ord(char) < 32 for char in unquote(ref))
            and not any(char in ref for char in "<>\\")
        )
    except ValueError:
        return False


class StaffEvidenceResolver:
    """No provider calls; optional live dependencies use their existing bounds."""

    def __init__(
        self,
        *,
        faq_service: Any = None,
        public_faq_service: Any = None,
        grounding_service: Any = None,
        network_status_service: Any = None,
        bisq_service: Any = None,
        before_live_read: Callable[[], Awaitable[bool]] | None = None,
        llm_wiki_loader: Any = None,
        llm_wiki_dir: Any = None,
    ) -> None:
        self.faq_service = faq_service
        self.public_faq_service = public_faq_service
        self.grounding_service = grounding_service
        self.network_status_service = network_status_service
        self.bisq_service = bisq_service
        self.before_live_read = before_live_read
        self.llm_wiki_loader = llm_wiki_loader
        self.llm_wiki_dir = llm_wiki_dir

    async def resolve(
        self, *, question: str, documents: list[Any], scores: list[float] | None = None
    ) -> EvidenceBundle:
        bundle = EvidenceBundle()
        candidates: list[ContextEvidence] = []
        current_compiled: dict[str, Any] = {}
        if self.llm_wiki_loader is not None and self.llm_wiki_dir is not None:
            try:
                pages = await asyncio.to_thread(
                    self.llm_wiki_loader.load_documents, self.llm_wiki_dir
                )
                current_compiled = {
                    str(page.metadata.get("id")): page for page in pages
                }
            except Exception:
                bundle.diagnostics.append("compiled_authority_unavailable")
        for document in documents[:32]:
            metadata = getattr(document, "metadata", {})
            if not isinstance(metadata, dict) or _private(metadata):
                bundle.diagnostics.append("private_or_invalid_document_excluded")
                continue
            try:
                kind = metadata.get("type")
                source: ContextEvidence | None = None
                if kind == "wiki":
                    source = self._wiki(document, metadata)
                elif kind == "faq":
                    source = self._faq(str(metadata.get("id") or ""))
                elif kind == "llm_wiki":
                    current = current_compiled.get(str(metadata.get("id")))
                    if current is not None and not _private(current.metadata):
                        # Use the current reviewed page, never a withdrawn/stale
                        # index snapshot. A long page can use an unchanged chunk.
                        content = current.page_content
                        if len(content) > 16000:
                            content = document.page_content
                            if content not in current.page_content:
                                content = ""
                        if content:
                            source = self._compiled(content, current.metadata)
                if source is not None:
                    candidates.append(source)
                    # FAQ refs resolve to actual published FAQ text. They remain
                    # independent evidence; the compiled body is not attributed to them.
                    if source.kind == "llm_wiki":
                        for ref in source.source_refs:
                            if ref.startswith("faq:"):
                                faq = self._faq(ref[4:])
                                if faq is not None:
                                    candidates.append(faq)
                else:
                    bundle.diagnostics.append(f"{kind or 'unknown'}_not_eligible")
            except (ValueError, TypeError, AttributeError):
                bundle.diagnostics.append("invalid_source_excluded")
        candidates.extend(await self._live(question, bundle))
        if self.grounding_service is not None:
            try:
                brief = await asyncio.to_thread(
                    self.grounding_service.build,
                    question=question,
                    knowledge_sources=[
                        {
                            **source.model_dump(),
                            "protocol": source.provenance.get("protocol"),
                        }
                        for source in candidates
                    ],
                )
                if isinstance(brief, dict):
                    bundle.internal_grounding = brief
                    candidates.extend(self._code(question, brief))
            except Exception:
                bundle.diagnostics.append("code_grounding_unavailable")
        # Retain source diversity before filling remaining slots in retrieval order.
        selected: list[ContextEvidence] = []
        seen: set[str] = set()
        kinds: set[str] = set()
        for source in candidates:
            if source.kind not in kinds:
                selected.append(source)
                seen.add(source.id)
                kinds.add(source.kind)
        for source in candidates:
            if source.id not in seen and len(selected) < 8:
                selected.append(source)
                seen.add(source.id)
        bundle.evidence = [
            source.model_copy(update={"id": f"e{index + 1}"})
            for index, source in enumerate(selected[:8])
        ]
        return bundle

    @staticmethod
    def _wiki(document: Any, metadata: dict[str, Any]) -> PublicEvidence | None:
        from app.services.rag.canonical_fixes import canonical_url_for_metadata
        from app.utils.wiki_url_generator import generate_wiki_url

        if (
            metadata.get("audience") not in (None, "public")
            or metadata.get("public") is False
        ):
            return None
        url = (
            metadata.get("url")
            or canonical_url_for_metadata(metadata)
            or generate_wiki_url(
                title=metadata.get("title"), section=metadata.get("section")
            )
        )
        content = document.page_content
        return PublicEvidence(
            id=_identifier("wiki", str(url) + content),
            kind="wiki",
            title=metadata.get("title"),
            content=content,
            url=url,
            provenance={
                "protocol": metadata.get("protocol"),
                "section": metadata.get("section"),
            },
        )

    def _faq(self, faq_id: str) -> PublicEvidence | None:
        from app.channels.plugins.support_markdown import BISQ2_FAQ_ONION_BASE_URL

        if not faq_id or self.faq_service is None or self.public_faq_service is None:
            return None
        row = self.faq_service.get_faq_by_id(faq_id)
        if (
            row is None
            or _value(row, "verified") is not True
            or str(_value(row, "id")) != faq_id
        ):
            return None
        question, answer = _value(row, "question"), _value(row, "answer")
        if not isinstance(question, str) or not isinstance(answer, str):
            return None
        published = self.public_faq_service.get_faq_by_id(faq_id)
        if (
            not published
            or str(published.get("id")) != faq_id
            or published.get("question") != question
            or published.get("answer") != answer
        ):
            return None
        slug = published.get("slug")
        if not isinstance(slug, str) or not SlugManager().validate_slug(slug):
            return None
        visible = self.public_faq_service.get_faq_by_slug(slug)
        if (
            not visible
            or str(visible.get("id")) != faq_id
            or visible.get("question") != question
            or visible.get("answer") != answer
        ):
            return None
        return PublicEvidence(
            id=_identifier("faq", faq_id),
            kind="faq",
            title=question[:160],
            content=f"Question: {question}\nAnswer: {answer}",
            url=f"{BISQ2_FAQ_ONION_BASE_URL.rstrip('/')}/faq/{slug}",
            source_refs=[f"faq:{faq_id}"],
            provenance={
                "faq_id": faq_id,
                "verified": True,
                "protocol": _value(row, "protocol"),
            },
        )

    @staticmethod
    def _compiled(content: str, metadata: dict[str, Any]) -> StaffEvidence | None:
        status = metadata.get("status")
        refs = metadata.get("source_refs")
        if (
            status not in {"reviewed", "active"}
            or not isinstance(refs, list)
            or not refs
            or metadata.get("audience") not in (None, "public", "staff_only")
        ):
            return None
        if len(refs) > 30 or not all(_valid_ref(ref) for ref in refs):
            return None
        page_id = str(metadata.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", page_id):
            return None
        return StaffEvidence(
            id=_identifier("compiled", page_id + content),
            kind="llm_wiki",
            title=metadata.get("title"),
            content=content,
            source_refs=refs,
            provenance={
                "page_id": page_id,
                "status": status,
                "protocol": metadata.get("protocol"),
                "page_type": metadata.get("page_type"),
                "reviewed_at": metadata.get("reviewed_at"),
                "reference_scope": "page_level_not_claim_level",
            },
        )

    @staticmethod
    def _code(question: str, brief: dict[str, Any]) -> list[StaffEvidence]:
        from app.services.rag.code_evidence import explicit_user_version

        version = explicit_user_version(question)
        evidence = []
        for fact in brief.get("evidence", [])[:3]:
            refs = fact.get("source_refs")
            if (
                fact.get("audience") != "staff_only"
                or not isinstance(refs, list)
                or not refs
            ):
                continue
            if not all(is_precise_code_source_ref(ref) for ref in refs):
                continue
            if version and (
                fact.get("freshness_class") != "release_bound"
                or version.removeprefix("v") not in fact.get("applies_to_versions", [])
            ):
                continue
            content = json.dumps(
                {
                    "claim": fact.get("claim"),
                    "support_use": fact.get("support_use"),
                    "source_releases": fact.get("applies_to_versions", []),
                    "freshness_class": fact.get("freshness_class"),
                    "user_version": version,
                    "limitations": brief.get("uncertainties", []),
                },
                ensure_ascii=False,
            )
            evidence.append(
                StaffEvidence(
                    id=_identifier("code", str(fact.get("id")) + content),
                    kind="code_fact",
                    title="Release-scoped implementation evidence",
                    content=content,
                    source_refs=refs,
                    provenance={
                        key: fact.get(key)
                        for key in (
                            "id",
                            "repo",
                            "commit",
                            "path",
                            "line_start",
                            "line_end",
                            "symbol",
                            "protocol",
                            "freshness_class",
                            "applies_to_versions",
                            "release_tag",
                            "source_sha256",
                        )
                    },
                )
            )
        return evidence

    async def _live(
        self, question: str, bundle: EvidenceBundle
    ) -> list[ContextEvidence]:
        from app.services.bisq_network_status_service import SCOPES
        from app.services.rag.llm_provider import (
            _detect_currency,
            needs_network_status,
            requested_network_status_areas,
        )

        evidence: list[ContextEvidence] = []
        if needs_network_status(question):
            areas = requested_network_status_areas(question)
            if not areas:
                bundle.diagnostics.append("network_scope_unestablished")
            for area in sorted(areas):
                if (
                    self.before_live_read is not None
                    and not await self.before_live_read()
                ):
                    bundle.diagnostics.append("live_read_deferred")
                    break
                if self.network_status_service is None:
                    bundle.diagnostics.append("monitoring_unavailable")
                    continue
                try:
                    report = await asyncio.wait_for(
                        self.network_status_service.get_status(area), timeout=10
                    )
                    if not isinstance(report, dict) or report.get("area") != area:
                        raise ValueError("Unexpected monitoring scope")
                    evidence.append(
                        PublicEvidence(
                            id=f"monitor-{area}",
                            kind="monitoring",
                            title=f"Bisq monitor: {area.replace('_', ' ')}",
                            content=json.dumps(report, ensure_ascii=False),
                            url=SCOPES[area].dashboard,
                            provenance={
                                "area": area,
                                "status": report.get("status"),
                                "checked_at": report.get("checked_at"),
                                "freshness": report.get("freshness"),
                                "coverage": SCOPES[area].coverage,
                            },
                        )
                    )
                except Exception:
                    bundle.diagnostics.append(f"monitoring_{area}_unavailable")
            return evidence
        if self.bisq_service is None:
            return evidence
        lower = question.casefold()
        currency = _detect_currency(question)
        tool, arguments = None, {}
        if re.search(r"\b(?:current|now|today|live|available)\b", lower):
            if re.search(r"\b(?:price|prices|rate)\b", lower):
                tool, arguments = "get_market_prices", {"currency": currency}
            elif re.search(r"\b(?:offers?|offerbook)\b", lower) and currency:
                tool, arguments = "get_offerbook", {"currency": currency}
            elif re.search(r"\bmarkets?\b", lower):
                tool = "get_markets"
        if tool is None:
            return evidence
        if self.before_live_read is not None and not await self.before_live_read():
            bundle.diagnostics.append("live_read_deferred")
            return evidence
        try:
            result = await asyncio.wait_for(
                getattr(self.bisq_service, tool)(**arguments), timeout=30
            )
            if not isinstance(result, dict):
                raise ValueError("Invalid live tool result")
            # Only market aggregates; do not copy counterparty/profile identifiers.
            fields = {
                "success",
                "timestamp",
                "currency_filter",
                "direction_filter",
                "total_count",
                "filtered_count",
                "prices",
                "markets",
            }
            safe_result = {key: value for key, value in result.items() if key in fields}
            if result.get("success") is not True:
                safe_result = {"success": False, "status": "unavailable"}
            checked = datetime.now(timezone.utc).isoformat()
            evidence.append(
                StaffEvidence(
                    id=_identifier("live", tool + json.dumps(arguments)),
                    kind="live_tool",
                    title="Configured Bisq 2 node observation",
                    content=json.dumps(
                        {
                            "tool": tool,
                            "arguments": arguments,
                            "checked_at": checked,
                            "result": safe_result,
                            "coverage": "Configured Bisq 2 node; cached observation timestamp is retained. Not every user's view or the entire network.",
                        },
                        ensure_ascii=False,
                    ),
                    provenance={
                        "tool": tool,
                        "checked_at": checked,
                        "observed_at": result.get("timestamp"),
                    },
                )
            )
        except Exception:
            bundle.diagnostics.append("bisq_live_tool_unavailable")
        return evidence

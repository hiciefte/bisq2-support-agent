"""Review-only Staff drafts, with rejected output retained for Admin inspection."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from app.channels.staff_assist.context_feedback import STAFF_CONTEXT_VERDICT_HINT
from app.channels.staff_assist.evidence_applicability import (
    source_applicability,
    staff_requester_product,
)
from app.channels.staff_assist.public_context import (
    ContextEvidence,
    PublicContextRequest,
    RoomMessage,
    _code_inspection_links,
    _guide_reference_links,
    _markdown_literal,
    _question_only,
)
from app.channels.staff_assist.staff_prompt import (
    STAFF_CONTEXT_PROMPT,
    SYNTHETIC_STAFF_EXAMPLES,
)
from app.prompts.runtime_policy import SAFETY_REFLEX_WARNING, should_apply_safety_reflex
from pydantic import BaseModel, ConfigDict, Field, ValidationError

PublicCitationReadiness = Literal[
    "not_applicable",
    "public_links_provided",
    "partial_public_links",
    "internal_evidence_only",
]


class StaffConversationCoverage(BaseModel):
    """Observed input boundaries, never a claim of complete room history."""

    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["unknown", "bounded_observed"] = "unknown"
    missing_parent_event_ids: list[str] = Field(default_factory=list, max_length=256)
    omitted_event_ids: list[str] = Field(default_factory=list, max_length=256)
    attachment_event_ids: list[str] = Field(default_factory=list, max_length=256)
    unselected_event_count: int = Field(default=0, ge=0)


class StaffContextRequest(PublicContextRequest):
    """A bounded attributed conversation; public preview limits stay unchanged."""

    question: str = Field(min_length=1, max_length=32000)
    recent_messages: list[RoomMessage] = Field(default_factory=list, max_length=128)
    audience: Literal["staff_only"] = "staff_only"
    conversation_coverage: StaffConversationCoverage = Field(
        default_factory=StaffConversationCoverage
    )


class StaffContextDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    reply: str = Field(max_length=10000)
    staff_note: str = Field(max_length=2000)
    source_ids: list[str] = Field(max_length=8)
    action: Literal["reply", "question", "silence"]
    reason: str = Field(min_length=1, max_length=500)


class StaffContextPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    decision: StaffContextDecision
    rendered_note: str | None = None
    requires_review: Literal[True] = True
    model_called: bool = False
    usage: dict[str, Any] | None = None
    validation_diagnostic: str | None = None
    rejected_draft: str | None = None
    knowledge_gap: str | None = None
    money_at_risk: bool = False
    examples_source: str = "synthetic_fallback"
    examples_sha256: str = ""
    source_applicability: dict[str, dict[str, Any]] = Field(default_factory=dict)
    public_citation_readiness: PublicCitationReadiness = "not_applicable"


def _silence(reason: str, **kwargs: Any) -> StaffContextPreview:
    return StaffContextPreview(
        decision=StaffContextDecision(
            reply="", staff_note="", source_ids=[], action="silence", reason=reason
        ),
        **kwargs,
    )


def load_staff_examples(
    data_dir: str | Path | None,
) -> tuple[list[dict[str, str]], str]:
    """Load locally reviewed, private style examples. Never fetch room history."""
    fallback = [dict(example) for example in SYNTHETIC_STAFF_EXAMPLES]
    if data_dir is None:
        return fallback, "synthetic_fallback"
    path = Path(data_dir) / "staff-context-examples.json"
    if not path.exists():
        return fallback, "synthetic_fallback"
    try:
        # A private example file must remain a small, explicitly reviewed corpus.
        if path.stat().st_size > 32000:
            raise ValueError("example file too large")
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
            raise ValueError("invalid example list")
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"reply"}:
                raise ValueError("invalid example schema")
            reply = row["reply"]
            if not isinstance(reply, str) or not reply.strip() or len(reply) > 1000:
                raise ValueError("invalid example reply")
            if re.search(
                r"@[\w.-]+(?::|\b)|\b[0-9a-f]{16,}\b|\b(?:bc1|tb1)[a-z0-9]{20,}\b",
                reply,
                re.I,
            ):
                raise ValueError("identifiers in example")
        return rows, "private_file"
    except (OSError, ValueError, TypeError):
        return fallback, "synthetic_fallback_invalid_file"


def _unsafe_reply(text: str) -> bool:
    """Check protected invariants; this is not a factual-quality grader."""
    secrets = r"(?:seed (?:words?|phrase)|recovery (?:words?|phrase|seed)|private keys?|mnemonic)"
    for clause in re.split(r"(?<=[.!?;])\s+|\n", text):
        for match in re.finditer(
            rf"\b(?:share|send|paste|provide|enter|give|upload|tell)\b.{{0,80}}?\b{secrets}\b",
            clause,
            re.I,
        ):
            # Negation must govern the solicitation verb, not an unrelated word
            # elsewhere in the sentence ("Never hesitate, send ...").
            prefix = clause[: match.start()]
            if not re.search(
                r"\b(?:never|do not|don't|don’t|must not)(?: ever)?\s+$", prefix, re.I
            ):
                return True
        if re.search(
            rf"\b(?:what|which)\b.{{0,40}}\b{secrets}\b.*[?？؟]", clause, re.I
        ):
            return True
        for match in re.finditer(
            r"\b(?:guaranteed|guarantee|will definitely|certainly will)\b", clause, re.I
        ):
            if not re.search(
                r"\b(?:no|not|never|cannot|can['’]t|isn['’]t|aren['’]t|"
                r"wasn['’]t|weren['’]t|won['’]t|doesn['’]t|don['’]t)"
                r"(?:\s+(?:a|an|any))?\s+$",
                clause[: match.start()],
                re.I,
            ):
                return True
    return bool(
        re.search(
            r"\b(?:staff|(?:the |your )?mediator|we|I) (?:has|have|already) (?:already )?"
            r"(?:acted|released|approved|processed|refunded|paid|contacted|resolved)\b",
            text,
            re.I,
        )
    )


def _money_at_risk_label(*texts: str) -> bool:
    """Conservative Staff display label, never a routing or safety decision."""
    text = "\n".join(texts)
    if re.search(
        r"\b(?:deposit(?:s|ed|ing)?|refund(?:s|ed|ing)?|payments?|pay-?outs?|escrow|"
        r"funds?|balances?|utxos?|unspent (?:transaction )?outputs?|withdrawals?|"
        r"mediation|arbitration)\b",
        text,
        re.I,
    ):
        return True
    asset = re.search(
        r"\b(?:btc|bsq|bitcoin|coins?|satoshis?|eur|usd)\b|[€$£¥]", text, re.I
    )
    movement = re.search(
        r"\b(?:send|sending|sent|transfer(?:s|red|ring)?|mov(?:e|ing)|release|"
        r"spend|spent|burn|pay|buy|sell|swap|withdraw|consolidat\w*)\b",
        text,
        re.I,
    )
    wallet_operation = re.search(
        r"\b(?:restor|recover|reset|sweep|empty|rebuild)\w*\b", text, re.I
    )
    return bool(
        (asset and movement)
        or (wallet_operation and re.search(r"\bwallets?\b", text, re.I))
    )


def _citations(source_ids: list[str], evidence: list[ContextEvidence]) -> str:
    sources = {source.id: source for source in evidence}
    links: list[str] = []
    for key in source_ids:
        source = sources[key]
        if source.url:
            link = (
                f"[{_markdown_literal(' '.join(source.title.split()))}]("
                + quote(source.url, safe=":/?#[]@!$&'()*+,;=%")
                + ")"
            )
        elif source.kind == "code_fact":
            refs = _code_inspection_links(source.source_refs)
            versions = source.provenance.get("applies_to_versions") or []
            link = (
                "Source release: "
                + _markdown_literal(", ".join(str(v) for v in versions))
                if versions
                else "Source release unconfirmed"
            )
            if refs:
                link += " · Further reading: " + " · ".join(refs)
        else:
            link = ""
        if link and link not in links:
            links.append(link)
    guides = _guide_reference_links(
        [
            ref
            for key in source_ids
            if sources[key].kind == "llm_wiki"
            for ref in sources[key].source_refs
        ]
    )
    if guides:
        links.append("Further reading: " + " · ".join(guides))
    return " · ".join(links)


class StaffContextService:
    """Generate and validate a human-reviewed reply; never send or train."""

    def __init__(self, llm: Any, *, data_dir: str | Path | None = None) -> None:
        self.llm = llm
        self.examples, self.examples_source = load_staff_examples(data_dir)
        self.examples_sha256 = hashlib.sha256(
            json.dumps(self.examples, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()

    def preview(self, request: StaffContextRequest) -> StaffContextPreview:
        product = staff_requester_product(request.question)
        applicability = {
            source.id: source_applicability(source, product=product)
            for source in request.evidence
        }
        eligible = [
            source
            for source in request.evidence
            if applicability[source.id]["eligible_for_reply"]
        ]
        money_at_risk = request.high_risk_action or _money_at_risk_label(
            request.question,
            *(
                message.content
                for message in request.recent_messages
                if message.role == "user"
            ),
        )
        common = {
            "money_at_risk": money_at_risk,
            "examples_source": self.examples_source,
            "examples_sha256": self.examples_sha256,
            "source_applicability": applicability,
        }
        if request.needs_moderation_review:
            return _silence("moderation_review_required", **common)
        if request.already_resolved or request.staff_active:
            return _silence("already_answered", **common)
        # Original bodies remain on the case's evidence snapshot. A conflicting
        # source cannot influence generation or be smuggled back by its ID.
        payload = {
            **request.model_dump(),
            "evidence": [source.model_dump() for source in eligible],
            "evidence_applicability": applicability,
            "style_examples": self.examples,
        }
        try:
            response = self.llm.invoke(
                json.dumps(payload, ensure_ascii=False),
                system_content=STAFF_CONTEXT_PROMPT,
            )
        except Exception:
            return _silence("generation_unavailable", model_called=True, **common)
        raw = getattr(response, "content", None)
        usage = getattr(response, "usage", None)
        if hasattr(usage, "model_dump"):
            usage = usage.model_dump()
        if not isinstance(usage, dict):
            usage = None
        diagnostic = "invalid_response"
        try:
            if not isinstance(raw, str):
                raise ValueError("response content must be text")
            diagnostic = "invalid_json"
            decoded = json.loads(raw)
            diagnostic = "invalid_schema"
            decision = StaffContextDecision.model_validate(decoded)
            money_at_risk = money_at_risk or _money_at_risk_label(
                decision.reply, decision.staff_note
            )
            common["money_at_risk"] = money_at_risk
            sources = {source.id for source in request.evidence}
            diagnostic = "unknown_or_duplicate_sources"
            if len(set(decision.source_ids)) != len(decision.source_ids) or any(
                key not in sources for key in decision.source_ids
            ):
                raise ValueError("invalid source IDs")
            diagnostic = "inapplicable_source"
            if any(
                not applicability[key]["eligible_for_reply"]
                for key in decision.source_ids
            ):
                raise ValueError("explicitly conflicting source cannot support draft")
            if decision.action == "silence":
                diagnostic = "invalid_silence"
                if decision.reply or decision.staff_note or decision.source_ids:
                    raise ValueError("silence must have empty content")
                gap = None
                if decision.reason.startswith("knowledge_gap:"):
                    gap = decision.reason.partition(":")[2].strip()[:200]
                    if not gap:
                        raise ValueError("knowledge gap needs a topic")
                elif decision.reason not in {"not_request", "already_answered"}:
                    raise ValueError("unsupported silence reason")
                return _silence(
                    decision.reason,
                    model_called=True,
                    usage=usage,
                    knowledge_gap=gap,
                    **common,
                )
            diagnostic = "missing_reply_or_staff_note"
            if not decision.reply.strip() or not decision.staff_note.strip():
                raise ValueError("reply and Staff note are required")
            diagnostic = "unsafe_reply"
            if _unsafe_reply(decision.reply) or _unsafe_reply(decision.staff_note):
                raise ValueError("protected invariant violated")
            if decision.action == "question":
                diagnostic = "invalid_question"
                if (
                    not _question_only(decision.reply)
                    or sum(decision.reply.count(mark) for mark in "?？؟") != 1
                ):
                    raise ValueError("ask one focused non-sensitive question")
            else:
                diagnostic = "invalid_question"
                if (
                    _question_only(decision.reply)
                    or sum(decision.reply.count(mark) for mark in "?？؟") > 1
                ):
                    raise ValueError("question-only output must use action question")
                diagnostic = "missing_reply_citation"
                if not decision.source_ids:
                    raise ValueError("factual reply needs evidence")
            # Prose stays literal; menu paths, symbols and length are not rejection
            # reasons. Only vetted evidence supplies clickable citations.
            warning = ""
            if (
                should_apply_safety_reflex(request.question)
                and SAFETY_REFLEX_WARNING not in decision.reply
            ):
                warning = SAFETY_REFLEX_WARNING + "\n\n"
            decision = decision.model_copy(
                update={
                    "reply": warning + decision.reply.strip(),
                    "staff_note": decision.staff_note.strip(),
                }
            )
            rendered = (
                "AI reply"
                + (" · money at risk" if money_at_risk else "")
                + "\n\n"
                + _markdown_literal(decision.reply)
            )
            rendered += "\n\nStaff note: " + _markdown_literal(decision.staff_note)
            links = _citations(decision.source_ids, request.evidence)
            if links:
                rendered += "\n\n" + links
            selected_sources = [
                source for source in eligible if source.id in decision.source_ids
            ]
            public_links = sum(bool(source.url) for source in selected_sources)
            citation_readiness: PublicCitationReadiness = (
                "not_applicable"
                if not selected_sources
                else (
                    "public_links_provided"
                    if public_links == len(selected_sources)
                    else (
                        "partial_public_links"
                        if public_links
                        else "internal_evidence_only"
                    )
                )
            )
            if citation_readiness in {"partial_public_links", "internal_evidence_only"}:
                rendered += "\n\nStaff source check: " + (
                    "Some supporting evidence has no public citation."
                    if public_links
                    else "Supporting evidence has no public citation."
                )
            diagnostic = "rendered_draft_too_long"
            if len(rendered) + len(STAFF_CONTEXT_VERDICT_HINT) + 2 > 10000:
                raise ValueError("case answer storage limit")
            return StaffContextPreview(
                decision=decision,
                rendered_note=rendered,
                model_called=True,
                usage=usage,
                money_at_risk=money_at_risk,
                examples_source=self.examples_source,
                examples_sha256=self.examples_sha256,
                source_applicability=applicability,
                public_citation_readiness=citation_readiness,
            )
        except (ValidationError, ValueError, TypeError, AttributeError):
            # Preserve the exact model text in the private case, including invalid
            # JSON and over-limit schema fields. Never log it or post it to Matrix.
            return _silence(
                "invalid_model_output",
                model_called=True,
                usage=usage,
                validation_diagnostic=diagnostic,
                rejected_draft=raw if isinstance(raw, str) else repr(raw),
                **common,
            )

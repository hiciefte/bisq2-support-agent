"""Conservative, non-mutating source checks for review-only Staff drafts.

These checks expose source declarations, not inferred user facts. They never
repair knowledge, infer a product from topic keywords, or verify a public page.
"""

from __future__ import annotations

import re
from typing import Any

from app.channels.staff_assist.public_context import ContextEvidence
from app.services.rag.code_evidence import explicit_product

_PRODUCTS = {
    "bisq1": "bisq1",
    "bisq": "bisq1",
    "multisig_v1": "bisq1",
    "bisq2": "bisq2",
    "bisq_easy": "bisq2",
    "musig": "bisq2",
}


def staff_requester_product(question: str) -> str | None:
    """Use affirmative own-product mentions only; ambiguity never quarantines.

    This deliberately errs toward unknown and leaves the public detector alone.
    It does not infer a product from error names, DAO terminology, or a version.
    """
    text = re.sub(r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`|(?m:^\s*>.*$)', "", question)
    if len(_named_products(text)) > 1 and re.search(
        r"\b(?:versus|vs|instead of|rather than|compar\w*|difference between)\b",
        text,
        re.I,
    ):
        return None
    products = set()
    for mention in re.finditer(
        r"\bbisq[ _-]?(?:1|2|easy)\b|\bmultisig(?:[ _-]?v?1)?\b|\bmusig\b",
        text,
        re.I,
    ):
        prefix = re.split(r"[.!?;,\n]", text[: mention.start()])[-1]
        if re.search(
            r"\b(?:not|never|no longer|don['’]t|isn['’]t|wasn['’]t|"
            r"if|whether|maybe|perhaps|assuming|suppose|could|would|might|unlike|versus|vs|"
            r"instead of|rather than|compared (?:to|with)|someone|somebody|"
            r"another (?:user|person)|they|says?|said|wrote|suggested)\b",
            prefix,
            re.I,
        ):
            continue
        if re.match(
            r"\s+(?:is|was)(?: not|n['’]t)\s+(?:what\b|the (?:one|product|app|application)\b|"
            r"my (?:product|app|application)\b|installed\b|in use\b)",
            text[mention.end() :],
            re.I,
        ):
            continue
        product = explicit_product(mention.group())
        if product:
            products.add(product)
    return products.pop() if len(products) == 1 else None


def _named_products(text: str) -> list[str]:
    named = []
    if re.search(r"\bbisq[ _-]?1\b", text, re.I):
        named.append("bisq1")
    if re.search(r"\bbisq[ _-]?(?:2|easy)\b", text, re.I):
        named.append("bisq2")
    return named


def source_applicability(
    source: ContextEvidence, *, product: str | None = None
) -> dict[str, Any]:
    """Block only explicit conflicts; leave missing/ambiguous scope unknown."""
    protocol = source.provenance.get("protocol")
    declared = _PRODUCTS.get(str(protocol or "").lower())
    text = source.title + "\n" + source.content
    named = _named_products(text)
    # A product mention in prose may be an exclusion or comparison. Only a
    # product-specific title or a leading explicit scope label supplies scope.
    scoped_product = staff_requester_product(source.title)
    if not scoped_product:
        label = re.match(
            r"^\s*(?:#+\s*)?(Bisq[ _-]?(?:1|2|easy))\s*:", source.content, re.I
        )
        if label:
            scoped_product = staff_requester_product(label.group(1))
    # A comparison page naming both products is ambiguous, not contradictory.
    single_named = scoped_product if len(named) == 1 else None
    reasons = []
    if declared and single_named and declared != single_named:
        reasons.append("source_product_metadata_conflict")
    scope = declared or single_named
    if product in {"bisq1", "bisq2"} and scope and product != scope:
        reasons.append("explicit_product_mismatch")
    return {
        "declared_protocol": protocol,
        "declared_product": declared,
        "explicitly_named_products": named,
        "explicit_text_scope": single_named,
        "requester_explicit_product": product,
        "eligible_for_reply": not reasons,
        "blocked_reasons": reasons,
        "product_scope": (
            "conflict" if reasons else "declared_not_verified" if scope else "unknown"
        ),
        "public_citation": (
            "vetted_url_not_live_checked" if source.url else "internal_only"
        ),
        "user_state_preconditions": "not_established_by_retrieval",
    }


def annotate_source(
    source: ContextEvidence, *, product: str | None = None
) -> ContextEvidence:
    """Keep exact content and original labels, adding separable review metadata."""
    return source.model_copy(
        update={
            "provenance": {
                **source.provenance,
                "staff_applicability": source_applicability(source, product=product),
            }
        }
    )

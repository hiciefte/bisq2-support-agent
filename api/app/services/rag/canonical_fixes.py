"""Curated issue-to-remedy mappings for recurring Bisq support problems.

The registry is intentionally small. Every URL and remedy must be backed by a
checked-in wiki page or reviewed support example; unmatched questions continue
through normal retrieval.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.services.rag.code_evidence import explicit_product
from langchain_core.documents import Document


@dataclass(frozen=True)
class CanonicalFix:
    """One human-curated fix selected by narrow issue signatures."""

    key: str
    title: str
    section: str
    url: str
    remedy: str
    protocol: str
    signatures: tuple[str, ...]
    # Explicit opt-in for published FAQ links, including reviewed legacy URLs.
    linked_reference_urls: tuple[str, ...] = ()

    def to_document(self) -> Document:
        """Render the fix as a small trusted retrieval document."""
        return Document(
            page_content=(
                "Curated canonical fix (maintainer-controlled):\n"
                f"{self.remedy}\n"
                f"Canonical link: {self.url}"
            ),
            metadata={
                "type": "wiki",
                "title": self.title,
                "section": self.section,
                "protocol": self.protocol,
                "url": self.url,
                "canonical_fix_id": self.key,
            },
        )


CANONICAL_FIXES: dict[str, CanonicalFix] = {
    # Section URL and conditions reviewed against the public FAQ on 2026-09-30.
    "payment-started-confirmation-loop": CanonicalFix(
        key="payment-started-confirmation-loop",
        title="Frequently asked questions",
        section='"Payment started" button won\'t stick / asks to send confirmation again.',
        url=(
            "https://bisq.wiki/Frequently_asked_questions#"
            "%22Payment_started%22_button_won%27t_stick_%2F_"
            "asks_to_send_confirmation_again."
        ),
        remedy=(
            "Bisq 1 documentation relates this payment-confirmation loop to P2P "
            "network conditions, often an offline peer; this does not establish "
            "the cause in this case. Documented options include trader chat, "
            "retrying the notification, restarting Bisq, the built-in outdated "
            "Tor-file refresh, and waiting while staying online. If the trade "
            "period is ending, the guide describes mediation. These are scoped "
            "documentation facts, not confirmation of the user's product, release "
            "or transaction state."
        ),
        protocol="multisig_v1",
        signatures=(
            r"payment started.{0,80}(?:will not|won't|doesn't|does not).{0,30}(?:stick|work)",
            r"payment started.{0,100}(?:please )?send (?:the )?confirmation again",
            r"(?:please )?send (?:the )?confirmation again.{0,100}payment started",
        ),
        linked_reference_urls=(
            "https://bisq.wiki/Frequently_asked_questions#"
            ".22Payment_started.22_button_will_not_stick.2C_always_says_"
            ".22Please_send_confirmation_again.22",
            "https://bisq.wiki/Frequently_asked_questions#"
            ".22Payment_started.22_button_will_not_stick.2C_always_says_"
            ".22Please_send_confirmation_again.22.",
        ),
    ),
    "incomplete-spv-resync": CanonicalFix(
        key="incomplete-spv-resync",
        title="Resyncing SPV file",
        section="Fix an Incomplete SPV Resync",
        url="https://bisq.wiki/Resyncing_SPV_file#Fix_an_Incomplete_SPV_Resync",
        remedy=(
            "For an interrupted Bisq 1 SPV resync that restarts from zero, close Bisq, "
            "remove only the documented resync marker, and restart."
        ),
        protocol="multisig_v1",
        signatures=(
            r"spv.{0,30}(?:resync|sync).{0,60}(?:incomplete|interrupt|stuck|freez|0%|zero)",
            r"(?:incomplete|interrupt|stuck|freez|0%|zero).{0,60}spv.{0,30}(?:resync|sync)",
            r"\bresyncspv\b",
        ),
    ),
    "move-bisq1-data-directory": CanonicalFix(
        key="move-bisq1-data-directory",
        title="Restoring application data",
        section="Restore an entire data directory",
        url=(
            "https://bisq.wiki/Restoring_application_data#"
            "Restore_an_entire_data_directory"
        ),
        remedy=(
            "To move Bisq 1, close it and copy the full data directory to the new "
            "installation; do not run the same wallet state in both places."
        ),
        protocol="multisig_v1",
        signatures=(
            r"(?:move|migrat|transfer|copy).{0,50}(?:bisq|data director(?:y|ies)).{0,60}(?:computer|machine|device|install)",
            r"(?:new|another).{0,20}(?:computer|machine|device).{0,60}(?:bisq|data director(?:y|ies))",
        ),
    ),
    "bisq1-account-signing": CanonicalFix(
        key="bisq1-account-signing",
        title="Account limits",
        section="Account signing",
        url="https://bisq.wiki/Account_limits#Account_signing",
        remedy=(
            "Bisq 1 account signing raises buying limits over time after a qualifying "
            "trade with an eligible signed peer account."
        ),
        protocol="multisig_v1",
        signatures=(
            r"\bwhat is (?:bisq 1 )?account signing\b",
            r"account sign(?:ing|ed).{0,80}(?:limit|buy|trade|how|when|eligible)",
            r"(?:how|when).{0,50}(?:get|become|make).{0,30}(?:account )?signed",
            r"signed account.{0,60}(?:limit|buy|trade)",
        ),
    ),
    "bisq1-open-mediation": CanonicalFix(
        key="bisq1-open-mediation",
        title="Dispute Resolution in Bisq 1",
        section="Level 2: Mediation",
        url=("https://bisq.wiki/Dispute_Resolution_in_Bisq_1#" "Level_2%3A_Mediation"),
        remedy=(
            "When Bisq 1 mediation is appropriate, select the open trade and use "
            "`Ctrl+O` (`Cmd+O` on macOS), then continue in the in-app ticket."
        ),
        protocol="multisig_v1",
        signatures=(
            r"\b(?:open|start|initiate|initiating)\b.{0,40}\b(?:mediation|dispute)\b",
            r"\b(?:mediation|dispute)\b.{0,40}\b(?:open|start|initiate|initiating)\b",
            r"\b(?:ctrl|cmd)\s*(?:\+|-)\s*o\b",
        ),
    ),
}


def _normalized_protocol(question: str, detected_version: str | None) -> str | None:
    normalized_version = str(detected_version or "").strip().casefold()
    if normalized_version in {"bisq 2", "bisq2", "bisq_easy", "bisq easy"}:
        return "bisq_easy"
    if normalized_version in {"bisq 1", "bisq1", "multisig_v1", "multisig"}:
        return "multisig_v1"

    lowered = question.casefold()
    if "bisq 2" in lowered or "bisq2" in lowered or "bisq easy" in lowered:
        return "bisq_easy"
    if "bisq 1" in lowered or "bisq1" in lowered or "multisig" in lowered:
        return "multisig_v1"
    return None


def find_canonical_fix(
    question: str, detected_version: str | None = None
) -> CanonicalFix | None:
    """Return at most one best verified fix for a narrowly matched question."""
    normalized_question = " ".join(str(question or "").casefold().split())
    if not normalized_question:
        return None

    question_protocol = _normalized_protocol(normalized_question, detected_version)
    if question_protocol is None:
        return None

    matches: list[tuple[int, int, CanonicalFix]] = []
    for priority, fix in enumerate(CANONICAL_FIXES.values()):
        if fix.protocol != question_protocol:
            continue
        score = _signature_score(fix, normalized_question)
        if score:
            matches.append((score, -priority, fix))

    if not matches:
        return None
    return max(matches, key=lambda item: (item[0], item[1]))[2]


def _signature_score(fix: CanonicalFix, normalized_question: str) -> int:
    return sum(
        1
        for signature in fix.signatures
        if re.search(signature, normalized_question, flags=re.IGNORECASE)
    )


def _linked_protocol(value: str) -> str | None:
    # Mixed product cues make explicit_product ambiguous; a MuSig mention must
    # still exclude this Bisq 1 guide rather than disappear in legacy routing.
    if re.search(r"\bmusig\b", value, re.IGNORECASE):
        return "musig"
    return _normalized_protocol(
        value.replace("_", " ").replace("-", " "), explicit_product(value)
    )


def find_linked_canonical_fix(
    question: str, reference_urls: set[str], product: str | None = None
) -> tuple[CanonicalFix, str] | None:
    """Resolve one reviewed FAQ association without inferring the user's product.

    Only explicitly opted-in entries may supply scoped documentation when the
    product is unknown. Question wording must also match the issue; the link or
    FAQ title alone cannot establish relevance.
    """
    normalized_question = " ".join(str(question or "").casefold().split())
    question_protocol = _linked_protocol(normalized_question)
    product_protocol = _linked_protocol(product or "")
    matches: list[tuple[int, int, CanonicalFix, str]] = []
    for priority, fix in enumerate(CANONICAL_FIXES.values()):
        if not fix.linked_reference_urls or any(
            protocol is not None and protocol != fix.protocol
            for protocol in (question_protocol, product_protocol)
        ):
            continue
        reference = next(
            (
                url
                for url in (fix.url, *fix.linked_reference_urls)
                if url in reference_urls
            ),
            None,
        )
        score = _signature_score(fix, normalized_question)
        if reference is not None and score:
            matches.append((score, -priority, fix, reference))
    if not matches:
        return None
    _, _, fix, reference = max(matches, key=lambda item: (item[0], item[1]))
    return fix, reference


def canonical_url_for_metadata(metadata: Mapping[str, Any]) -> str | None:
    """Return a registry URL only for an exact ID-and-URL metadata match."""
    fix_id = metadata.get("canonical_fix_id")
    explicit_url = metadata.get("url")
    if not isinstance(fix_id, str) or not isinstance(explicit_url, str):
        return None

    fix = CANONICAL_FIXES.get(fix_id)
    if fix is None or explicit_url != fix.url:
        return None
    return fix.url


def _is_strict_canonical_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "bisq.wiki"
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
        )
    except (TypeError, ValueError):
        return False


def validate_canonical_fixes() -> None:
    """Raise when a curated entry violates static safety invariants."""
    for key, fix in CANONICAL_FIXES.items():
        if key != fix.key:
            raise ValueError(f"canonical fix key mismatch: {key!r} != {fix.key!r}")
        if not _is_strict_canonical_url(fix.url):
            raise ValueError(f"canonical fix URL is not allowlisted: {fix.url!r}")
        if any(not _is_strict_canonical_url(url) for url in fix.linked_reference_urls):
            raise ValueError(
                f"canonical fix linked reference is not allowlisted: {key}"
            )
        if not fix.remedy.strip() or "\n" in fix.remedy:
            raise ValueError(f"canonical fix remedy must be one non-empty line: {key}")


validate_canonical_fixes()

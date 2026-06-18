"""Shared topic clustering for LLM Wiki knowledge updates."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from app.services.training.unified_repository import UnifiedFAQCandidate

TOKEN_STOPWORDS = {
    "about",
    "after",
    "answer",
    "bisq",
    "from",
    "have",
    "that",
    "this",
    "user",
    "with",
    "what",
    "when",
    "where",
    "will",
    "your",
}

TOPIC_CLUSTER_MIN_SIZE = 3
TOPIC_CLUSTER_MAX_SIZE = 5

TOPIC_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "open_mediation_or_support_ticket",
        (
            r"\bopen (a )?(mediation|support ticket|dispute)\b",
            r"\b(start|request|initiate) (mediation|a support ticket)\b",
            r"\bctrl\s*\+?\s*o\b",
            r"\bcmd\s*\+?\s*o\b",
            r"\bmediator\b",
        ),
    ),
    (
        "unresponsive_peer_or_release",
        (
            r"\b(seller|buyer|peer|counterparty).*(not respond|unresponsive|offline|does not answer)\b",
            r"\b(payment received|confirm receipt|release btc|release bitcoin)\b",
            r"\btrade (deadline|timer|period|window).*(expired|exceeded|approaching)\b",
        ),
    ),
    (
        "payment_account_or_name_mismatch",
        (
            r"\b(account|bank|iban|zelle|sepa|wise|revolut).*(name|owner|mismatch|different|wrong)\b",
            r"\bpayment account\b",
            r"\baccount owner\b",
        ),
    ),
    (
        "wallet_restore_or_data_directory",
        (
            r"\b(seed words|wallet seed|backup|restore|data directory|new instance|old wallet)\b",
            r"\bcopy.*bisq (folder|directory)\b",
            r"\bimport.*wallet\b",
        ),
    ),
    (
        "wallet_sync_or_spv",
        (
            r"\b(spv|resync|confirmations|mempool|wallet balance|missing transaction)\b",
            r"\bdeposit.*(confirmed|missing|null)\b",
            r"\b0 confirmations\b",
        ),
    ),
    (
        "tor_network_or_price_feed",
        (r"\b(tor|peer|peers|bitcoin network|price feed|price node|connection)\b",),
    ),
    (
        "account_signing_or_limits",
        (r"\b(signed|signing|account limits|trade limits|new account)\b",),
    ),
    (
        "payment_method_reversibility_or_chargeback",
        (
            r"\b(chargeback|recall|reversible|payment method|zelle|sepa|ach|wise|strike)\b",
        ),
    ),
    (
        "bisq_easy_reputation_or_risk",
        (r"\b(bisq easy|reputation|seller reputation|mediation in bisq 2)\b",),
    ),
)

ROUTING_PRIORITY = {
    "FULL_REVIEW": 0,
    "SPOT_CHECK": 1,
    "AUTO_APPROVE": 2,
}


@dataclass(frozen=True)
class KnowledgeTopicCluster:
    key: str
    topic: str
    candidates: Sequence[UnifiedFAQCandidate]

    @property
    def size(self) -> int:
        return len(self.candidates)

    @property
    def candidate_ids(self) -> list[int]:
        return [candidate.id for candidate in self.candidates]

    def examples(self, limit: int = 5) -> list[dict[str, str | int]]:
        return [
            {
                "candidate_id": candidate.id,
                "question": _clean(
                    candidate.edited_question_text or candidate.question_text
                ),
                "answer": _clean(
                    candidate.edited_staff_answer or candidate.staff_answer
                ),
            }
            for candidate in self.candidates[:limit]
        ]

    def to_response(self, limit: int = 5) -> dict[str, object]:
        return {
            "key": self.key,
            "topic": self.topic,
            "size": self.size,
            "candidate_ids": self.candidate_ids,
            "examples": self.examples(limit=limit),
        }


@dataclass(frozen=True)
class KnowledgeReviewItem:
    candidate: UnifiedFAQCandidate
    routing: str
    cluster: KnowledgeTopicCluster | None = None


def build_knowledge_review_items(
    candidates: Sequence[UnifiedFAQCandidate],
    is_reviewable: Callable[[UnifiedFAQCandidate], bool],
    *,
    cluster_key: Callable[[UnifiedFAQCandidate], str] | None = None,
) -> list[KnowledgeReviewItem]:
    """Collapse reviewable topic clusters into one admin queue item."""
    ordered = [candidate for candidate in candidates if is_reviewable(candidate)]
    indexed = {candidate.id: index for index, candidate in enumerate(ordered)}
    clusters = build_topic_clusters(ordered, key_func=cluster_key)
    clustered_ids: set[int] = set()
    items: list[tuple[int, KnowledgeReviewItem]] = []

    for key, group in clusters.items():
        if len(group) < TOPIC_CLUSTER_MIN_SIZE or len(group) > TOPIC_CLUSTER_MAX_SIZE:
            continue
        clustered_ids.update(candidate.id for candidate in group)
        routing = min(
            (candidate.routing for candidate in group),
            key=lambda value: ROUTING_PRIORITY.get(value, 99),
        )
        representative = next(
            candidate for candidate in group if candidate.routing == routing
        )
        cluster = KnowledgeTopicCluster(
            key=key,
            topic=_topic_from_key(key),
            candidates=group,
        )
        items.append(
            (
                min(indexed[candidate.id] for candidate in group),
                KnowledgeReviewItem(
                    candidate=representative,
                    routing=routing,
                    cluster=cluster,
                ),
            )
        )

    for candidate in ordered:
        if candidate.id in clustered_ids:
            continue
        items.append(
            (
                indexed[candidate.id],
                KnowledgeReviewItem(candidate=candidate, routing=candidate.routing),
            )
        )

    return [item for _, item in sorted(items, key=lambda entry: entry[0])]


def build_exact_clusters(
    candidates: Iterable[UnifiedFAQCandidate],
) -> dict[str, list[int]]:
    clusters: dict[str, list[int]] = defaultdict(list)
    for candidate in candidates:
        clusters[exact_cluster_key(candidate)].append(candidate.id)
    return dict(clusters)


def build_topic_clusters(
    candidates: Iterable[UnifiedFAQCandidate],
    *,
    key_func: Callable[[UnifiedFAQCandidate], str] | None = None,
) -> dict[str, list[UnifiedFAQCandidate]]:
    clusters: dict[str, list[UnifiedFAQCandidate]] = defaultdict(list)
    build_key = key_func or topic_cluster_key
    for candidate in candidates:
        clusters[build_key(candidate)].append(candidate)
    return dict(clusters)


def topic_cluster_ids(
    candidates: Iterable[UnifiedFAQCandidate],
) -> dict[str, list[int]]:
    return {
        key: [candidate.id for candidate in group]
        for key, group in build_topic_clusters(candidates).items()
    }


def exact_cluster_key(candidate: UnifiedFAQCandidate) -> str:
    question = _fingerprint(candidate.edited_question_text or candidate.question_text)
    answer = _fingerprint(candidate.edited_staff_answer or candidate.staff_answer)
    return (
        f"{candidate.protocol or 'none'}|{candidate.category or 'none'}|"
        f"{question}|{answer}"
    )


def topic_cluster_key(candidate: UnifiedFAQCandidate) -> str:
    text = _clean(
        " ".join(
            [
                candidate.edited_question_text or candidate.question_text,
                candidate.edited_staff_answer or candidate.staff_answer,
                candidate.category or "",
            ]
        )
    )
    lowered = text.lower()
    for label, patterns in TOPIC_PATTERNS:
        if any(re.search(pattern, lowered) for pattern in patterns):
            return f"{candidate.protocol or 'none'}|{label}"

    tokens = [
        token
        for token in re.findall(r"[a-z0-9]{4,}", lowered)
        if token not in TOKEN_STOPWORDS
    ]
    counts = Counter(tokens)
    keywords = "-".join(token for token, _ in counts.most_common(4))
    return f"{candidate.protocol or 'none'}|{candidate.category or 'none'}|{keywords}"


def _topic_from_key(key: str) -> str:
    return key.rsplit("|", 1)[-1]


def _fingerprint(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value).lower())
    return " ".join(normalized.split())


def _clean(value: str) -> str:
    return " ".join(str(value or "").split())

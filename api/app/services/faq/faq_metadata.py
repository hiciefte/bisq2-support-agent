"""FAQ metadata normalization and inference helpers.

These helpers ensure new FAQs always have both `category` and `protocol` set.
"""

from typing import Dict, Literal, Optional, Tuple, cast

FAQProtocol = Literal["multisig_v1", "bisq_easy", "musig", "all"]

_CATEGORY_KEYWORDS = {
    "Trading": (
        3,
        [
            "trade",
            "offer",
            "maker",
            "taker",
            "price",
            "spread",
            "mediation",
            "arbitration",
            "settle",
        ],
    ),
    "Wallet": (
        3,
        [
            "wallet",
            "seed",
            "restore",
            "backup",
            "address",
            "txid",
            "transaction id",
            "utxo",
            "keys",
        ],
    ),
    "Security": (
        3,
        ["security", "scam", "phishing", "tor", "pgp", "signature", "verify", "fraud"],
    ),
    "Reputation": (
        3,
        ["reputation", "profile age", "profile", "badge", "score", "burn bsq"],
    ),
    "Payments": (
        3,
        ["payment", "bank", "sepa", "iban", "wise", "revolut", "zelle", "fiat", "ach"],
    ),
    "Technical": (
        2,
        [
            "error",
            "crash",
            "install",
            "upgrade",
            "update",
            "version",
            "log",
            "broken",
            "stuck",
        ],
    ),
    "Fees": (2, ["fee", "fees", "mining fee", "network fee"]),
    "Account": (2, ["account", "login", "sign in", "identity", "session"]),
    "Bisq Easy": (2, ["bisq easy"]),
    "Bisq 2": (2, ["bisq 2", "bisq2"]),
}


def _sanitize(text: Optional[str]) -> str:
    return (text or "").lower()


def infer_protocol(question: Optional[str], answer: Optional[str]) -> FAQProtocol:
    """Infer FAQ protocol from question/answer content."""
    combined = f"{_sanitize(question)} {_sanitize(answer)}".strip()
    has_bisq2 = "bisq easy" in combined or "bisq 2" in combined or "bisq2" in combined
    has_bisq1 = "bisq 1" in combined or "bisq1" in combined or "multisig" in combined
    has_musig = "musig" in combined

    if has_musig and not has_bisq1 and not has_bisq2:
        return "musig"
    if has_bisq1 and has_bisq2:
        return "all"
    if has_bisq1:
        return "multisig_v1"
    if has_bisq2:
        return "bisq_easy"
    return "all"


def infer_category(
    question: Optional[str],
    answer: Optional[str],
    fallback_category: Optional[str] = None,
) -> str:
    """Infer FAQ category from content, preserving explicit user choice."""
    preferred = (fallback_category or "").strip()
    if preferred and preferred.lower() != "general":
        return preferred

    combined = f"{_sanitize(question)} {_sanitize(answer)}".strip()
    if not combined:
        return "General"

    scores: Dict[str, int] = {category: 0 for category in _CATEGORY_KEYWORDS}
    for category, (weight, keywords) in _CATEGORY_KEYWORDS.items():
        for token in keywords:
            if token in combined:
                scores[category] += weight

    best_category = "General"
    best_score = 0
    for category, score in scores.items():
        if score > best_score:
            best_category = category
            best_score = score

    if best_score > 0:
        return best_category
    return preferred or "General"


def normalize_faq_metadata(
    question: Optional[str],
    answer: Optional[str],
    category: Optional[str],
    protocol: Optional[str],
) -> Tuple[str, FAQProtocol]:
    """Return normalized (category, protocol) for FAQ creation."""
    normalized_category = infer_category(question, answer, category)
    if protocol in {"multisig_v1", "bisq_easy", "musig", "all"}:
        normalized_protocol = cast(FAQProtocol, protocol)
    else:
        normalized_protocol = infer_protocol(question, answer)
    return normalized_category, normalized_protocol

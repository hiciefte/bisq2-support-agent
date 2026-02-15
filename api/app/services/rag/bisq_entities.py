"""Bisq domain entity mappings — single source of truth.

Used by:
- ProtocolDetector: keyword lists for version routing
- QueryRewriter: heuristic entity substitution + LLM prompt generation
"""

# Maps informal term → canonical form (for heuristic substitution)
BISQ1_ENTITY_MAP: dict[str, str] = {
    # Informal version references (mined from 44K Matrix messages)
    "old bisq": "Bisq 1",
    "old version": "Bisq 1",
    "the old one": "Bisq 1",
    "original bisq": "Bisq 1",
    "classic bisq": "Bisq 1",
    "v1": "Bisq 1",
    "version 1": "Bisq 1",
    # Technical terms (Bisq 1 only)
    "spv resync": "SPV resync (Bisq 1)",
    "data directory": "Bisq 1 data directory",
    "data dir": "Bisq 1 data directory",
    "signed account": "signed account (Bisq 1)",
    "account signing": "account signing (Bisq 1)",
    "account age witness": "account age witness (Bisq 1)",
    # Protocol synonyms
    "multi-sig": "multisig",
    "multi sig": "multisig",
    "2of2": "2-of-2 multisig",
    "escrow": "multisig escrow (Bisq 1)",
    "bsq swap": "BSQ swap (Bisq 1)",
}

BISQ2_ENTITY_MAP: dict[str, str] = {
    # Informal version references
    "new bisq": "Bisq 2",
    "new version": "Bisq 2",
    "v2": "Bisq 2",
    "version 2": "Bisq 2",
    # Feature-specific terms
    "reputation score": "Bisq Easy reputation score",
    "reputation system": "Bisq Easy reputation system",
    "easy trade": "Bisq Easy trade",
    "chat trade": "Bisq Easy chat-based trade",
    "chat based": "Bisq Easy chat-based trading",
}

# Strong keywords for ProtocolDetector (existing + expanded)
BISQ1_STRONG_KEYWORDS: list[str] = [
    # Original ProtocolDetector keywords
    "dao",
    "bsq",
    "burningman",
    "burning man",
    "arbitration",
    "arbitrator",
    "altcoin",
    "security deposit",
    "multisig",
    "2-of-2",
    "delayed payout",
    "refund agent",
    "dao voting",
    # From entity map
    *BISQ1_ENTITY_MAP.keys(),
    # Additional strong signals from Matrix data
    "spv",
    "buy bsq",
    "pay in bsq",
    "maker fee",
    "taker fee",
    "donation address",
    "1.9.",
    "1.8.",
    "1.7.",
]

BISQ2_STRONG_KEYWORDS: list[str] = [
    # Original ProtocolDetector keywords
    "bisq easy",
    "reputation",
    "bonded roles",
    "trade protocol",
    "multiple identities",
    "600 usd",
    "$600",
    "novice bitcoin",
    "bisq 2",
    "bisq2",
    "current price",
    "market price",
    "live price",
    "btc price",
    "bitcoin price",
    "offerbook",
    "current offers",
    "available offers",
    "active offers",
    # From entity map
    *BISQ2_ENTITY_MAP.keys(),
    # Additional strong signals
    "2.0.",
    "2.1.",
]


def build_llm_entity_examples() -> str:
    """Generate entity mapping examples for the LLM rewriter prompt.

    Auto-generated from the entity maps so the prompt stays in sync.
    """
    b1 = [
        f'   - "{k}" \u2192 "{v}"'
        for k, v in BISQ1_ENTITY_MAP.items()
        if k != v.lower()
    ]
    b2 = [
        f'   - "{k}" \u2192 "{v}"'
        for k, v in BISQ2_ENTITY_MAP.items()
        if k != v.lower()
    ]
    # Interleave to ensure both Bisq 1 and Bisq 2 examples appear
    lines: list[str] = []
    for pair in zip(b1, b2):
        lines.extend(pair)
    lines.extend(b1[len(b2) :] or b2[len(b1) :])
    return "\n".join(lines[:10])  # Cap at 10 examples to keep prompt short

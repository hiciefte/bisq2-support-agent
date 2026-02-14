"""Shared utilities for query context analysis.

Used by QueryRewriter (heuristic track) and potentially ProtocolDetector.
"""

import re
from typing import Dict, List, Optional

# Anaphoric pronoun patterns (compiled once)
_ANAPHORIC_RE = re.compile(r"\b(it|that|this|those|these|they|them)\b", re.IGNORECASE)
_DEICTIC_RE = re.compile(
    r"\b(the same|the above|what you said|you mentioned|like that)\b",
    re.IGNORECASE,
)

# Short acknowledgments that should be skipped when looking for topic context.
# Matches single acks or common combos like "ok thanks", "yes sure", "got it thanks".
_ACK_WORDS = (
    r"ok|okay|yes|no|sure|thanks|thank you|got it|i see|right|alright|"
    r"cool|great|fine|hmm|ah|oh|yep|nope|k|thx|ty"
)
_ACK_RE = re.compile(
    rf"^({_ACK_WORDS})(\s*[,.]?\s*({_ACK_WORDS}))*\s*[.!?]*$",
    re.IGNORECASE,
)


def is_anaphoric(query: str) -> bool:
    """Check if query contains anaphoric references that need resolution."""
    return bool(_ANAPHORIC_RE.search(query) or _DEICTIC_RE.search(query))


def _is_substantive(content: str) -> bool:
    """Check if a message is substantive (not just an acknowledgment)."""
    stripped = content.strip()
    if len(stripped) <= 5:
        return False
    if _ACK_RE.match(stripped):
        return False
    return True


def extract_last_topic(
    chat_history: List[Dict[str, str]], max_chars: int = 100
) -> Optional[str]:
    """Extract the topic from the most recent substantive user message.

    Skips acknowledgments ("ok", "thanks", "got it") and very short messages
    to find the actual topic the user was discussing. The current query being
    rewritten must NOT be included in chat_history.

    Truncates at natural sentence boundary under max_chars.
    """
    for msg in reversed(chat_history):
        if msg.get("role") == "user":
            content = msg.get("content", "").strip()
            if _is_substantive(content):
                if len(content) > max_chars:
                    boundary = content[:max_chars].rfind(". ")
                    if boundary > 20:
                        return content[: boundary + 1]
                    return content[:max_chars]
                return content
    return None


def extract_topic_keywords(topic: str, max_keywords: int = 5) -> str:
    """Extract key domain terms from a topic string for search context.

    Returns a compact keyword string suitable for appending to a query,
    rather than prepending the full topic sentence.
    """
    # Remove common stop words to extract meaningful terms
    stop_words = {
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "the",
        "a",
        "an",
        "is",
        "am",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "can",
        "may",
        "might",
        "shall",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "about",
        "into",
        "through",
        "during",
        "before",
        "after",
        "and",
        "but",
        "or",
        "so",
        "if",
        "then",
        "than",
        "that",
        "this",
        "it",
        "its",
        "just",
        "also",
        "very",
        "really",
        "want",
        "need",
        "like",
        "think",
        "know",
        "see",
        "get",
        "set",
        "up",
        "out",
        "how",
        "what",
        "when",
        "where",
        "which",
    }
    words = re.findall(r"\b[a-zA-Z0-9]+\b", topic.lower())
    keywords = [w for w in words if w not in stop_words and len(w) > 2]
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return " ".join(unique[:max_keywords])

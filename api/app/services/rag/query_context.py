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


def is_anaphoric(query: str) -> bool:
    """Check if query contains anaphoric references that need resolution."""
    return bool(_ANAPHORIC_RE.search(query) or _DEICTIC_RE.search(query))


def extract_last_topic(
    chat_history: List[Dict[str, str]], max_chars: int = 100
) -> Optional[str]:
    """Extract the topic from the most recent user message in chat history.

    Truncates at natural sentence boundary under max_chars.
    """
    for msg in reversed(chat_history):
        if msg.get("role") == "user":
            content = msg.get("content", "").strip()
            if content and len(content) > 5:
                if len(content) > max_chars:
                    boundary = content[:max_chars].rfind(". ")
                    if boundary > 20:
                        return content[: boundary + 1]
                    return content[:max_chars]
                return content
    return None

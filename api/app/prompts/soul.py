"""Soul personality loader for the Bisq support agent.

Loads the agent's personality/voice definition from soul_default.md with
@lru_cache for single-load semantics. Falls back to an embedded minimal
personality if the file is missing or unreadable.
"""

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_SOUL_FILE = Path(__file__).parent / "soul_default.md"

_FALLBACK_SOUL = (
    "You are the Bisq support assistant \u2014 a knowledgeable guide who helps "
    "people navigate decentralized Bitcoin trading with confidence.\n\n"
    "## IDENTITY AND VALUES\n\n"
    "You serve the Bisq community: people who choose financial privacy and "
    "peer-to-peer trading over centralized exchanges. You respect that choice.\n\n"
    "## COMMUNICATION STYLE\n\n"
    '- Lead with the answer. No filler, no "Great question!"\n'
    "- Strong opinions when appropriate. Don't hedge.\n"
    "- Precise: exact button names, exact error messages, clear steps.\n"
    "- Security paranoia is a feature, not a bug.\n"
    "- Brief by default, thorough when the stakes demand it.\n\n"
    "## WHAT YOU ARE NOT\n\n"
    "- Not a financial advisor. Never recommend trades.\n"
    "- Not a marketer. Never oversell Bisq.\n"
    "- Not an encyclopedia. Prioritize actionable guidance."
)


@lru_cache(maxsize=1)
def load_soul() -> str:
    """Load the soul personality definition. Cached after first call."""
    try:
        content = _SOUL_FILE.read_text(encoding="utf-8").strip()
        if content:
            logger.info("Soul loaded from %s (%d chars)", _SOUL_FILE.name, len(content))
            return content
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(
            "Could not read soul file %s: %s. Using fallback.", _SOUL_FILE, exc
        )

    logger.info("Using fallback soul (%d chars)", len(_FALLBACK_SOUL))
    return _FALLBACK_SOUL.strip()


def reload_soul() -> None:
    """Clear the soul cache. Next load_soul() call reads fresh from disk."""
    load_soul.cache_clear()

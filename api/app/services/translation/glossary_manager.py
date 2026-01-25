"""Glossary Manager for preserving domain-specific terminology during translation.

This module protects Bisq-specific terms from being translated, ensuring
technical accuracy in multilingual support.
"""

import re
from typing import ClassVar, Dict, Optional, Tuple


class GlossaryManager:
    """Preserves domain-specific terminology during translation.

    Bisq-specific terms like "Bisq Easy", "BTC", "multisig" should never
    be translated as they are proper nouns or technical terms.
    """

    # Bisq-specific terms that should NEVER be translated
    PROTECTED_TERMS: ClassVar[Dict[str, str]] = {
        # Core Bisq concepts
        "Bisq": "Bisq",
        "Bisq 2": "Bisq 2",
        "Bisq Easy": "Bisq Easy",
        "Bisq 1": "Bisq 1",
        # Cryptocurrency terms
        "BTC": "BTC",
        "Bitcoin": "Bitcoin",
        "BSQ": "BSQ",
        "satoshi": "satoshi",
        "sats": "sats",
        # Technical terms
        "multisig": "multisig",
        "2-of-2 multisig": "2-of-2 multisig",
        "security deposit": "security deposit",
        "trade protocol": "trade protocol",
        "reputation system": "reputation system",
        "bonded roles": "bonded roles",
        # Entities and roles
        "DAO": "DAO",
        "arbitrator": "arbitrator",
        "mediator": "mediator",
        "maker": "maker",
        "taker": "taker",
        # Trade terms
        "offer": "offer",
        "offerbook": "offerbook",
        "trade": "trade",
    }

    def __init__(self, additional_terms: Optional[Dict[str, str]] = None):
        """Initialize the GlossaryManager.

        Args:
            additional_terms: Optional dict of additional terms to protect.
        """
        self.terms = {**self.PROTECTED_TERMS}
        if additional_terms:
            self.terms.update(additional_terms)

        # Build regex pattern for efficient matching
        # Sort by length (longest first) to match "Bisq Easy" before "Bisq"
        escaped_terms = [
            re.escape(t) for t in sorted(self.terms.keys(), key=len, reverse=True)
        ]
        self.pattern = re.compile(
            r"\b(" + "|".join(escaped_terms) + r")\b", re.IGNORECASE
        )

    def protect_terms(self, text: str) -> Tuple[str, Dict[str, str]]:
        """Replace protected terms with placeholders.

        This should be called BEFORE sending text to translation API.

        Args:
            text: Input text that may contain protected terms.

        Returns:
            Tuple of (modified_text, placeholder_map) where:
            - modified_text: Text with terms replaced by placeholders
            - placeholder_map: Dict mapping placeholder -> original term
        """
        placeholder_map: Dict[str, str] = {}
        counter = [0]  # Use list for closure modification

        def replace_with_placeholder(match: re.Match) -> str:
            term = match.group(0)
            placeholder = f"__BISQ_TERM_{counter[0]}__"
            placeholder_map[placeholder] = term
            counter[0] += 1
            return placeholder

        protected_text = self.pattern.sub(replace_with_placeholder, text)
        return protected_text, placeholder_map

    def restore_terms(self, text: str, placeholder_map: Dict[str, str]) -> str:
        """Restore original terms from placeholders.

        This should be called AFTER receiving translated text.

        Args:
            text: Translated text containing placeholders.
            placeholder_map: Dict mapping placeholder -> original term.

        Returns:
            Text with placeholders replaced by original terms.
        """
        result = text
        for placeholder, original in placeholder_map.items():
            result = result.replace(placeholder, original)
        return result

    def add_term(self, term: str) -> None:
        """Add a new protected term.

        Args:
            term: The term to protect from translation.
        """
        self.terms[term] = term
        # Rebuild pattern with new term
        escaped_terms = [
            re.escape(t) for t in sorted(self.terms.keys(), key=len, reverse=True)
        ]
        self.pattern = re.compile(
            r"\b(" + "|".join(escaped_terms) + r")\b", re.IGNORECASE
        )

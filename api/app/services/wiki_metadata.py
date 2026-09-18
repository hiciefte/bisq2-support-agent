"""Reviewed wiki classifications that override incidental protocol mentions."""

from typing import Optional


def reviewed_wiki_category(title: str) -> Optional[str]:
    """Return an audited article category, or defer to normal classification."""
    normalized_title = " ".join(title.replace("_", " ").lower().split())
    # This article describes the legacy multisig wallet/deposit requirements.
    # Its Bisq Easy paragraph recommends a way to acquire the initial bitcoin;
    # it does not make those requirements applicable to Bisq Easy.
    if normalized_title == "funding your wallet":
        return "bisq1"
    return None

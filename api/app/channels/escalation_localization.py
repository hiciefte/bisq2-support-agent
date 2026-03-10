"""Localized escalation notice rendering."""

from __future__ import annotations

from typing import Optional

from app.channels.translations import (
    DEFAULT_ESCALATION_CHANNEL,
    DEFAULT_ESCALATION_LOCALE,
    ESCALATION_NOTICE_CATALOG,
    ESCALATION_NOTICE_CHANNEL_KEYS,
)
from app.channels.translations.catalog import normalize_locale_tag


def normalize_language_code(language_code: Optional[str]) -> str:
    """Normalize language code to a stable locale tag with safe fallback."""
    normalized = normalize_locale_tag(language_code)
    if len(normalized) > 32:
        return DEFAULT_ESCALATION_LOCALE
    return normalized or DEFAULT_ESCALATION_LOCALE


def render_escalation_notice(
    *,
    channel_id: str,
    escalation_id: int,
    support_handle: str,
    language_code: Optional[str] = None,
) -> str:
    """Render a localized escalation notice with graceful English fallback."""
    lang = normalize_language_code(language_code)
    primary_key = ESCALATION_NOTICE_CHANNEL_KEYS.get(channel_id) or ESCALATION_NOTICE_CHANNEL_KEYS[
        DEFAULT_ESCALATION_CHANNEL
    ]
    generic_key = ESCALATION_NOTICE_CHANNEL_KEYS[DEFAULT_ESCALATION_CHANNEL]
    return ESCALATION_NOTICE_CATALOG.format(
        key=primary_key,
        locale=lang,
        fallback_keys=(generic_key,),
        params={
            "support_handle": support_handle,
            "escalation_id": escalation_id,
        },
    )

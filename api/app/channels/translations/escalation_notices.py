"""Escalation notice i18n constants and catalog wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from app.channels.translations.catalog import JsonMessageCatalog, normalize_locale_tag
from app.channels.translations.supported_locales import BISQ2_SUPPORTED_LOCALES_WITH_EN

DEFAULT_ESCALATION_LOCALE: Final[str] = "en"
DEFAULT_ESCALATION_CHANNEL: Final[str] = "generic"

ESCALATION_NOTICE_CHANNEL_KEYS: Final[dict[str, str]] = {
    "generic": "escalation.notice.generic",
    "web": "escalation.notice.web",
    "matrix": "escalation.notice.matrix",
    "bisq2": "escalation.notice.bisq2",
}

ESCALATION_NOTICE_REQUIRED_KEYS: Final[frozenset[str]] = frozenset(
    ESCALATION_NOTICE_CHANNEL_KEYS.values()
)

ESCALATION_NOTICE_LOCALE_DIR: Final[Path] = (
    Path(__file__).resolve().parent / "locales" / "escalation_notices"
)

ESCALATION_NOTICE_REQUIRED_LOCALES: Final[frozenset[str]] = frozenset(
    normalize_locale_tag(locale) for locale in BISQ2_SUPPORTED_LOCALES_WITH_EN
)

ESCALATION_NOTICE_CATALOG = JsonMessageCatalog(
    base_dir=ESCALATION_NOTICE_LOCALE_DIR,
    default_locale=DEFAULT_ESCALATION_LOCALE,
    required_keys=ESCALATION_NOTICE_REQUIRED_KEYS,
    required_locales=ESCALATION_NOTICE_REQUIRED_LOCALES,
)

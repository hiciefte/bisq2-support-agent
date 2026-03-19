"""Chat UI label i18n constants and catalog wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from app.channels.translations.catalog import JsonMessageCatalog, normalize_locale_tag
from app.channels.translations.supported_locales import BISQ2_SUPPORTED_LOCALES_WITH_EN

DEFAULT_CHAT_UI_LOCALE: Final[str] = "en"

CHAT_UI_LABEL_KEYS: Final[dict[str, str]] = {
    "helpful_prompt": "chat.ui.helpful_prompt",
    "helpful_thank_you": "chat.ui.helpful_thank_you",
    "staff_helpful_prompt": "chat.ui.staff_helpful_prompt",
    "staff_response_label": "chat.ui.staff_response_label",
    "support_team_notified": "chat.ui.support_team_notified",
}

CHAT_UI_REQUIRED_KEYS: Final[frozenset[str]] = frozenset(CHAT_UI_LABEL_KEYS.values())

CHAT_UI_LOCALE_DIR: Final[Path] = (
    Path(__file__).resolve().parent / "locales" / "chat_ui_labels"
)

CHAT_UI_REQUIRED_LOCALES: Final[frozenset[str]] = frozenset(
    normalize_locale_tag(locale) for locale in BISQ2_SUPPORTED_LOCALES_WITH_EN
)

CHAT_UI_LABEL_CATALOG = JsonMessageCatalog(
    base_dir=CHAT_UI_LOCALE_DIR,
    default_locale=DEFAULT_CHAT_UI_LOCALE,
    required_keys=CHAT_UI_REQUIRED_KEYS,
    required_locales=CHAT_UI_REQUIRED_LOCALES,
)


def get_chat_ui_labels(language_code: str | None) -> dict[str, str]:
    """Resolve localized UI labels for web chat widgets."""
    locale = normalize_locale_tag(language_code)
    return {
        label_name: CHAT_UI_LABEL_CATALOG.format(
            key=translation_key,
            locale=locale,
        )
        for label_name, translation_key in CHAT_UI_LABEL_KEYS.items()
    }

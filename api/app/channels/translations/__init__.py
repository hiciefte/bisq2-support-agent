"""Channel translation catalogs."""

from app.channels.translations.chat_ui_labels import (
    CHAT_UI_LABEL_CATALOG,
    CHAT_UI_LABEL_KEYS,
    DEFAULT_CHAT_UI_LOCALE,
    get_chat_ui_labels,
)
from app.channels.translations.escalation_notices import (
    DEFAULT_ESCALATION_CHANNEL,
    DEFAULT_ESCALATION_LOCALE,
    ESCALATION_NOTICE_CATALOG,
    ESCALATION_NOTICE_CHANNEL_KEYS,
)

__all__ = [
    "CHAT_UI_LABEL_CATALOG",
    "CHAT_UI_LABEL_KEYS",
    "DEFAULT_ESCALATION_CHANNEL",
    "DEFAULT_CHAT_UI_LOCALE",
    "DEFAULT_ESCALATION_LOCALE",
    "ESCALATION_NOTICE_CATALOG",
    "ESCALATION_NOTICE_CHANNEL_KEYS",
    "get_chat_ui_labels",
]

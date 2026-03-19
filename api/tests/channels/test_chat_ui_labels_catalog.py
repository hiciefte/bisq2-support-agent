from app.channels.translations.chat_ui_labels import (
    CHAT_UI_LABEL_CATALOG,
    CHAT_UI_LABEL_KEYS,
    CHAT_UI_REQUIRED_LOCALES,
    DEFAULT_CHAT_UI_LOCALE,
    get_chat_ui_labels,
)


def test_catalog_contains_all_required_locale_files():
    loaded = set(CHAT_UI_LABEL_CATALOG.translations.keys())
    assert CHAT_UI_REQUIRED_LOCALES.issubset(loaded)


def test_catalog_resolves_default_locale_labels():
    labels = get_chat_ui_labels(DEFAULT_CHAT_UI_LOCALE)
    assert set(labels.keys()) == set(CHAT_UI_LABEL_KEYS.keys())
    assert labels["helpful_prompt"] == "Was this response helpful?"


def test_catalog_locale_fallback_for_region_tag():
    labels = get_chat_ui_labels("de-CH")
    assert labels["staff_response_label"].lower().startswith("antwort")


def test_catalog_normalizes_underscore_locale_tag():
    labels = get_chat_ui_labels("pt_BR")
    assert labels["helpful_prompt"].strip()
    assert labels["helpful_prompt"] != "Was this response helpful?"

from app.channels.translations.escalation_notices import (
    DEFAULT_ESCALATION_CHANNEL,
    DEFAULT_ESCALATION_LOCALE,
    ESCALATION_NOTICE_CATALOG,
    ESCALATION_NOTICE_CHANNEL_KEYS,
    ESCALATION_NOTICE_REQUIRED_LOCALES,
)
from app.channels.translations.supported_locales import (
    BISQ2_SUPPORTED_LOCALES_54,
    BISQ2_SUPPORTED_LOCALES_WITH_EN,
)


def test_bisq2_supported_locale_count_matches_expected():
    assert len(BISQ2_SUPPORTED_LOCALES_54) == 54
    assert len(BISQ2_SUPPORTED_LOCALES_WITH_EN) == 55


def test_catalog_contains_all_required_locale_files():
    loaded = set(ESCALATION_NOTICE_CATALOG.translations.keys())
    assert ESCALATION_NOTICE_REQUIRED_LOCALES.issubset(loaded)


def test_catalog_resolves_default_channel_and_locale():
    default_key = ESCALATION_NOTICE_CHANNEL_KEYS[DEFAULT_ESCALATION_CHANNEL]
    text = ESCALATION_NOTICE_CATALOG.resolve_template(
        key=default_key,
        locale=DEFAULT_ESCALATION_LOCALE,
    )
    assert text.strip()


def test_catalog_locale_fallback_for_region_and_channel():
    # de-CH locale file is intentionally absent; this should fall back to de.
    text = ESCALATION_NOTICE_CATALOG.format(
        key=ESCALATION_NOTICE_CHANNEL_KEYS["web"],
        locale="de-CH",
        fallback_keys=(ESCALATION_NOTICE_CHANNEL_KEYS[DEFAULT_ESCALATION_CHANNEL],),
        params={},
    )
    assert text.startswith("Ich markiere das")


def test_catalog_normalizes_underscore_locale_tag():
    text = ESCALATION_NOTICE_CATALOG.format(
        key=ESCALATION_NOTICE_CHANNEL_KEYS["web"],
        locale="pt_BR",
        fallback_keys=(ESCALATION_NOTICE_CHANNEL_KEYS[DEFAULT_ESCALATION_CHANNEL],),
        params={},
    )
    assert text.strip()
    assert "team member" not in text.lower()

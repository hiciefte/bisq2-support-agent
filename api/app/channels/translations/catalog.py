"""Generic JSON-backed message catalog with locale fallback and validation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

_PLACEHOLDER_PATTERN = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)}")


def normalize_locale_tag(locale: str | None) -> str:
    """Normalize locale tags to lowercase BCP47-ish style (pt-BR -> pt-br)."""
    normalized = str(locale or "").strip().replace("_", "-").lower()
    if not normalized:
        return "en"
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized


def build_locale_fallback_chain(locale: str | None, default_locale: str) -> list[str]:
    """Build locale fallback chain: de-CH -> de -> en."""
    requested = normalize_locale_tag(locale)
    fallback = normalize_locale_tag(default_locale)

    chain: list[str] = []
    if requested:
        chain.append(requested)
        if "-" in requested:
            base = requested.split("-", 1)[0]
            if base and base not in chain:
                chain.append(base)

    if fallback not in chain:
        chain.append(fallback)
    return chain


class JsonMessageCatalog:
    """Load and validate locale message catalogs from JSON files."""

    def __init__(
        self,
        *,
        base_dir: Path,
        default_locale: str,
        required_keys: Iterable[str],
        required_locales: Iterable[str],
    ) -> None:
        self.base_dir = Path(base_dir)
        self.default_locale = normalize_locale_tag(default_locale)
        self.required_keys = frozenset(str(k).strip() for k in required_keys if str(k).strip())
        self.required_locales = frozenset(
            normalize_locale_tag(locale) for locale in required_locales
        )
        self.translations = self._load_translations()
        self._validate_catalog()

    def _load_translations(self) -> dict[str, dict[str, str]]:
        if not self.base_dir.exists():
            raise ValueError(f"Catalog directory does not exist: {self.base_dir}")

        catalogs: dict[str, dict[str, str]] = {}
        for file_path in sorted(self.base_dir.glob("*.json")):
            locale = normalize_locale_tag(file_path.stem)
            raw_data = json.loads(file_path.read_text(encoding="utf-8"))
            if not isinstance(raw_data, dict):
                raise ValueError(
                    f"Catalog file must contain a JSON object: {file_path}"
                )

            message_map: dict[str, str] = {}
            for key, value in raw_data.items():
                normalized_key = str(key or "").strip()
                if not normalized_key:
                    continue
                text = str(value or "").strip()
                if text:
                    message_map[normalized_key] = text
            catalogs[locale] = message_map

        return catalogs

    @staticmethod
    def _extract_placeholders(text: str) -> set[str]:
        return set(_PLACEHOLDER_PATTERN.findall(str(text or "")))

    def _validate_catalog(self) -> None:
        if self.default_locale not in self.translations:
            raise ValueError(
                f"Default locale file missing: {self.default_locale}.json in {self.base_dir}"
            )

        missing_locale_files = sorted(
            locale
            for locale in self.required_locales
            if locale not in self.translations
        )
        if missing_locale_files:
            raise ValueError(
                f"Missing locale files in {self.base_dir}: {', '.join(missing_locale_files)}"
            )

        default_messages = self.translations[self.default_locale]
        missing_default_keys = sorted(
            key for key in self.required_keys if key not in default_messages
        )
        if missing_default_keys:
            raise ValueError(
                f"Default locale '{self.default_locale}' is missing keys: {', '.join(missing_default_keys)}"
            )

        for locale in sorted(self.required_locales):
            messages = self.translations[locale]
            missing_keys = sorted(key for key in self.required_keys if key not in messages)
            if missing_keys:
                raise ValueError(
                    f"Locale '{locale}' missing required keys: {', '.join(missing_keys)}"
                )

            for key in self.required_keys:
                expected = self._extract_placeholders(default_messages[key])
                actual = self._extract_placeholders(messages[key])
                if expected != actual:
                    raise ValueError(
                        "Placeholder mismatch for locale "
                        f"'{locale}' key '{key}': expected {sorted(expected)}, got {sorted(actual)}"
                    )

    def resolve_template(
        self,
        *,
        key: str,
        locale: str | None,
        fallback_keys: Iterable[str] = (),
    ) -> str:
        """Resolve template with locale + key fallback."""
        primary_key = str(key or "").strip()
        keys = [primary_key, *[str(k).strip() for k in fallback_keys if str(k).strip()]]
        if not primary_key:
            raise KeyError("Message key must not be empty")

        chain = build_locale_fallback_chain(locale, self.default_locale)
        for locale_candidate in chain:
            locale_messages = self.translations.get(locale_candidate, {})
            for candidate_key in keys:
                template = locale_messages.get(candidate_key)
                if template:
                    return template

        raise KeyError(
            f"Unable to resolve message key '{primary_key}' for locale '{locale}'"
        )

    def format(
        self,
        *,
        key: str,
        locale: str | None,
        params: Mapping[str, Any] | None = None,
        fallback_keys: Iterable[str] = (),
    ) -> str:
        """Resolve and format a message template."""
        template = self.resolve_template(
            key=key,
            locale=locale,
            fallback_keys=fallback_keys,
        )
        payload = dict(params or {})
        try:
            return template.format(**payload)
        except KeyError as exc:
            missing = str(exc).strip("'")
            raise ValueError(
                f"Missing template parameter '{missing}' for key '{key}'"
            ) from exc

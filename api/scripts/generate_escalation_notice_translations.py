#!/usr/bin/env python3
"""Generate escalation notice translations for all supported Bisq locales.

This script translates the escalation notice message catalog into all
Bisq-supported locales using the configured LLM provider.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import aisuite as ai  # type: ignore[import-untyped]

# Allow running as standalone script.
API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.channels.translations.catalog import normalize_locale_tag
from app.channels.translations.supported_locales import BISQ2_SUPPORTED_LOCALES_WITH_EN

MODEL_DEFAULT = "openai:gpt-4o-mini"
CATALOG_DIR = (
    API_ROOT / "app" / "channels" / "translations" / "locales" / "escalation_notices"
)

SOURCE_MESSAGES = {
    "escalation.notice.generic": (
        "I'm flagging this for a team member who can review the details. "
        "Someone will follow up here shortly."
    ),
    "escalation.notice.web": (
        "I'm flagging this for a team member who can review the details. "
        "Someone will follow up here shortly."
    ),
    "escalation.notice.matrix": (
        "This needs a team member's attention. Someone will follow up in this room."
    ),
    "escalation.notice.bisq2": (
        "This needs a team member's attention. Someone will follow up in this conversation."
    ),
}

RESPONSE_KEYS = tuple(SOURCE_MESSAGES.keys())


def _extract_json_object(text: str) -> dict[str, str]:
    content = str(text or "").strip()
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        raise ValueError("Model response did not contain a JSON object")

    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Model response JSON root must be an object")
    return {str(k): str(v) for k, v in parsed.items()}


def _validate_payload(payload: dict[str, str]) -> dict[str, str]:
    keys = tuple(payload.keys())
    if set(keys) != set(RESPONSE_KEYS):
        raise ValueError(
            f"Unexpected translation keys. expected={sorted(RESPONSE_KEYS)} got={sorted(keys)}"
        )

    normalized: dict[str, str] = {}
    for key in RESPONSE_KEYS:
        text = str(payload.get(key, "") or "").strip()
        if not text:
            raise ValueError(f"Empty translation for key '{key}'")
        normalized[key] = text
    return normalized


def _translate_locale(
    *,
    client: ai.Client,
    model: str,
    locale_tag: str,
    max_retries: int = 3,
) -> dict[str, str]:
    if locale_tag == "en":
        return dict(SOURCE_MESSAGES)

    prompt_payload = json.dumps(SOURCE_MESSAGES, ensure_ascii=False, indent=2)
    system_prompt = (
        "You are an expert software localization translator for fintech support chat. "
        "Return ONLY valid JSON with exactly the same keys as provided. "
        "Do not add or remove keys. Keep meaning precise, concise, and human. "
        "No markdown, no explanations."
    )
    user_prompt = (
        f"Target locale: {locale_tag}\n"
        "Translate the following JSON values from English into the target locale.\n"
        "Use natural tone suitable for user-facing support escalation notices.\n"
        "JSON:\n"
        f"{prompt_payload}"
    )

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=600,
                temperature=0,
            )
            text = str(response.choices[0].message.content or "").strip()
            parsed = _extract_json_object(text)
            return _validate_payload(parsed)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == max_retries:
                break
            time.sleep(0.6 * attempt)
    raise RuntimeError(
        f"Failed translation for locale '{locale_tag}' after {max_retries} attempts: {last_error}"
    )


def _write_locale_file(locale_tag: str, payload: dict[str, str]) -> Path:
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    locale_file = CATALOG_DIR / f"{normalize_locale_tag(locale_tag)}.json"
    locale_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return locale_file


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate escalation notice translations for all supported locales."
    )
    parser.add_argument("--model", default=MODEL_DEFAULT, help="Model identifier")
    parser.add_argument(
        "--locales",
        default="all",
        help="Comma-separated locale list (default: all supported locales)",
    )
    args = parser.parse_args()

    if args.locales.strip().lower() == "all":
        locales = list(BISQ2_SUPPORTED_LOCALES_WITH_EN)
    else:
        locales = [x.strip() for x in args.locales.split(",") if x.strip()]

    client = ai.Client()
    total = len(locales)
    print(f"Generating translations for {total} locales using model={args.model}...")

    for idx, locale in enumerate(locales, start=1):
        locale_norm = normalize_locale_tag(locale)
        translated = _translate_locale(
            client=client,
            model=args.model,
            locale_tag=locale_norm,
        )
        path = _write_locale_file(locale_norm, translated)
        print(f"[{idx}/{total}] wrote {path.name}")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

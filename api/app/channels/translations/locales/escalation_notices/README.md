# Escalation Notice Locale Files

This directory contains one JSON file per locale for escalation notices.

## File naming

- Use normalized locale tags in lowercase with `-` separators.
- Examples: `en.json`, `de.json`, `pt-br.json`, `zh-hans.json`.

## Required keys

Every locale file must include all keys below:

- `escalation.notice.generic`
- `escalation.notice.web`
- `escalation.notice.matrix`
- `escalation.notice.bisq2`

## Fallback behavior

- Locale fallback chain: `language-region` -> `language` -> `en`.
- Channel fallback chain: channel-specific key -> `escalation.notice.generic`.

## Placeholder rules

If a key contains placeholders (e.g. `{escalation_id}`), all locales must preserve
exactly the same placeholder names.

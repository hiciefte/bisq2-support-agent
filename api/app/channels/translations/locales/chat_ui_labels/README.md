# Chat UI Label Locale Files

This directory contains one JSON file per locale for web chat UI labels.

## File naming

- Use normalized locale tags in lowercase with `-` separators.
- Examples: `en.json`, `de.json`, `pt-br.json`, `zh-hans.json`.

## Required keys

Every locale file must include all keys below:

- `chat.ui.helpful_prompt`
- `chat.ui.helpful_thank_you`
- `chat.ui.staff_helpful_prompt`
- `chat.ui.staff_response_label`
- `chat.ui.support_team_notified`

## Fallback behavior

- Locale fallback chain: `language-region` -> `language` -> `en`.

# Internal LLM Wiki Schema

The internal LLM Wiki is the compiled support-intelligence layer for the Bisq Support Agent. It is not the external Bisq wiki and it is not a public FAQ store.

## Source Roles

- `bisq.wiki`: external canonical product documentation.
- `faqs.db`: public, short, user-facing Q/A entries.
- Support conversations: raw evidence only.
- Internal LLM Wiki: reviewed support knowledge synthesized from evidence and used by RAG.

## Page Frontmatter

Required for pages under `pages/`:

```yaml
---
id: stable-kebab-case-id
title: Human-readable title
type: llm_wiki
page_type: support_playbook
status: draft | proposed | reviewed | active | deprecated
protocol: bisq_easy | multisig_v1 | all
reviewed_by: reviewer-id
reviewed_at: "YYYY-MM-DD"
risk_level: low | medium | high
source_refs:
  - wiki:Page Title
  - faq:123
---
```

Only `reviewed` and `active` pages are indexable by the local loader. Production activation should use `active` pages once the eval gate is implemented.

## Page Structure

Use these sections for `page_type: support_playbook`:

1. `## Canonical Support Answer`
2. `## Applies When`
3. `## Do Not Say`
4. `## Evidence / Sources`
5. `## Review Notes`
6. `## Last Change Summary`

## Review Rules

- Every operational instruction must be backed by `source_refs` or explicitly marked as a review note.
- Prefer stable support behavior over one-off chat phrasing.
- Do not copy private user details from support conversations.
- Do not create public FAQs from support chats by default.
- Prefer small diffs to existing pages over creating new pages.
- If an issue is unresolved, keep it in `Review Notes` and avoid turning it into canonical guidance.

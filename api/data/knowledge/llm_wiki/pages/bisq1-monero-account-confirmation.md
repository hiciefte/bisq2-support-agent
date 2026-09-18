---
id: bisq1-monero-account-confirmation
title: Bisq 1 Monero receiving accounts and auto-confirm
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
risk_level: medium
source_refs:
- https://bisq.wiki/Trading_Monero
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/desktop/src/main/java/bisq/desktop/main/settings/preferences/PreferencesView.java#L888
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/desktop/src/main/java/bisq/desktop/components/paymentmethods/XmrForm.java
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
---
## Monero receiving accounts and auto-confirm

Create an XMR receiving account under Account > Altcoins using an address you have verified in your own Monero wallet. Bisq’s automatic subaddress generation is optional and separate from XMR auto-confirm; leave that advanced mode unused unless its configuration and generated address are verified. Auto-confirm checks receipt of XMR, whereas you can check actual wallet receipt and confirm manually. In 1.9.18 a network filter can disable the auto-confirm settings group, so a grey control alone is not proof of its saved setting or a wallet-address error. Do not bypass a disabled feature; verify payment in your wallet before confirming.

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 707. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Evidence / Sources

- https://bisq.wiki/Trading_Monero
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/desktop/src/main/java/bisq/desktop/main/settings/preferences/PreferencesView.java#L888
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/desktop/src/main/java/bisq/desktop/components/paymentmethods/XmrForm.java

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

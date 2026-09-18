---
id: bisq-support-privacy-safety
title: Verifying support and sharing diagnostic information safely
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: all
risk_level: high
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
source_refs:
- https://bisq.wiki/Dispute_resolution
- https://bisq.wiki/Data_directory
- https://bisq.wiki/Dispute_Resolution_in_Bisq_2
- https://github.com/mempool/mempool/blob/874670fed804d092ade021d0ae74d109c7d61475/backend/src/config.ts
- https://mempool.space/
---
## Canonical Support Answer

Treat unsolicited private support messages and links as untrusted. A familiar display name does not prove identity. Verify the contact through an established official Bisq support channel before following instructions, installing software or sending funds.

Support does not need seed words, wallet passwords or private keys to diagnose a problem in chat. Never publish them or enter them into an unverified site or application. Do not convert a particular staff member's invitation to DM into a permanent contact instruction for everyone, or assert an unsupported universal policy about who can initiate a message.

Share the application/version, exact error and relevant logs or transaction evidence through an appropriate verified channel. Review logs and screenshots for personal or financial information; send only what is needed and redact unrelated details. Confirm the recipient and sharing method before uploading bank evidence. A public file-host link can expose it to anyone with access to the link.

For a live trade dispute, prefer its built-in trade/mediation conversation so the evidence stays attached to the case. If that fails, use established support to reach the proper mediator. Keep protocol-specific recovery and payment decisions with the actual trade context.

## Authenticating the mempool.space Tor endpoint

For the mempool.space explorer, obtain its onion endpoint from the official project rather than trusting a pasted chat address. The official mempool/mempool source publishes it as EXTERNAL_DATA_SERVER.MEMPOOL_ONION in backend/src/config.ts. The immutable source below records the value reviewed; consult the current official reference when connecting because service endpoints can change. This named explorer is distinct from the general Bitcoin mempool concept.

## Evidence / Sources

- https://bisq.wiki/Dispute_resolution
- https://bisq.wiki/Data_directory
- https://bisq.wiki/Dispute_Resolution_in_Bisq_2

- https://github.com/mempool/mempool/blob/874670fed804d092ade021d0ae74d109c7d61475/backend/src/config.ts
- https://mempool.space/

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 1409. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

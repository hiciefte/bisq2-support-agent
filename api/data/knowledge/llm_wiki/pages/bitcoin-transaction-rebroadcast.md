---
id: bitcoin-transaction-rebroadcast
title: Rebroadcasting an existing Bitcoin transaction
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: all
risk_level: medium
source_refs:
- https://developer.bitcoin.org/reference/rpc/sendrawtransaction.html
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
---
## Rebroadcasting an existing signed transaction

Rebroadcasting sends the same already-signed transaction to the network; it is not a new payment or a fee increase. Use the originating wallet’s documented feature if available, or a trusted Bitcoin node’s sendrawtransaction facility with that transaction’s signed hex. Confirm the transaction and its purpose first. Never supply seed words or private keys to a broadcaster. Manual rebroadcast can reveal the transaction’s origin, and a rejected transaction needs its rejection reason investigated. Do not manually publish a Bisq delayed payout outside the eligible arbitration workflow.

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 2379. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Evidence / Sources

- https://developer.bitcoin.org/reference/rpc/sendrawtransaction.html

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

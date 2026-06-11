---
id: bisq1-altcoin-instant-stuck
title: Bisq 1 Altcoin Instant trade protocol not progressing
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: codex-initial-llm-wiki-review
reviewed_at: "2026-05-13"
risk_level: high
source_refs:
  - wiki:Dispute Resolution in Bisq 1
  - wiki:Mediation
  - wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees
  - wiki:Deposit transaction
---
## Canonical Support Answer

If an Altcoin Instant or Bisq 1 trade starts but protocol state stops progressing, avoid guessing from the state label alone. First determine whether the deposit transaction exists and whether the maker/taker fee transactions are valid. If funds may be locked or payment has already been sent, keep the trade open and use trader chat or mediation.

For protocol failures, the mediator can request transaction IDs, logs, and payment proof. If the issue is caused by invalid or missing transactions, handle it as a failed-trade case; if the deposit is valid and the peer/payment side is disputed, handle it through dispute resolution.

## Applies When

- The user says Altcoin Instant or Bisq 1 protocol state is stuck.
- The user asks whether to cancel, delete, or retry a stuck trade.
- The user reports output/cancelled state after payment or confirmation.

## Do Not Say

- Do not tell users to delete the trade before checking transaction state.
- Do not conflate failed transaction creation with a live dispute over locked funds.
- Do not provide payout conclusions before mediator review.

## Evidence / Sources

- `wiki:Dispute Resolution in Bisq 1` documents trader chat, mediation, and arbitration paths.
- `wiki:Mediation` documents mediator transaction checks and proof collection.
- `wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees` distinguishes failed transaction cases.
- `wiki:Deposit transaction` explains deposit txid verification.

## Review Notes

- Specific Altcoin Instant state names should be mapped against current Bisq 1 logs/UI when available.

## Last Change Summary

Converted from generated support playbook into internal LLM Wiki page; ready for local support-admin review.

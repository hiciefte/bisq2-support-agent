---
id: bisq1-bitcoin-transaction-status
title: Bisq 1 wallet transaction status and replacement boundaries
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: high
source_refs:
- https://bisq.wiki/Deposit_transaction_pending_in_mempool_and_CPFP
- https://bisq.wiki/Resyncing_SPV_file
- https://bisq.wiki/Support_Agent_Knowledge_Base
- https://bisq.wiki/Wallet
- https://bisq.wiki/Import_Bisq_wallet_as_watch_only_wallet_in_Sparrow
- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/core/src/main/java/bisq/core/trade/validation/DepositTxValidation.java
- https://bisq.wiki/Deposit_transaction
---
## Canonical Support Answer

Identify the actual Bitcoin transaction ID and whether it is external funding, a wallet withdrawal, maker/taker fee, trade deposit, normal payout or delayed payout. A withdrawal is not a trade and has no trade ID. Check current confirmations, fee rate, unconfirmed ancestors and input/output state before choosing a remedy.

A pending transaction has no fixed global expiry. One explorer dropping it does not guarantee every node forgot it or that a second payment is safe. SPV resync refreshes local state, not network validity; it cannot cancel a still-valid transaction. An ETA is only an estimate and may change with network demand.

CPFP spends an eligible controlled output and aims to confirm parent and child together. Replacement spends conflicting inputs under applicable wallet/network rules. These are different operations, and fees must be assessed for the relevant package rather than by a universal multiplier. For an ordinary withdrawal, a suitable receiving or change output may permit CPFP in a wallet that supports it, after checking cost and eligibility. For a trade, additional protocol dependencies apply: never treat a locked multisig deposit as a normal spendable output or replace trade funding as a generic cancellation method.

Do not import or expose wallet secrets, create a second payment or construct a replacement transaction merely because time elapsed. Preserve the transaction evidence and ask verified support to assess unclear state. Use the deposit, failed-trade or payout page for its specific branch.

For a confirmed transfer, establish the destination and direction first: an external withdrawal is not an incoming Bisq balance. Compare an incoming output with the intended Bisq receiving address, and use the deposit or payout workflow for a trade transaction.

For inspection, the official watch-only Sparrow guide can expose the relevant BTC history without importing a seed; it cannot sign or replace a transaction. It does not make a timed conflicting spend safe.

## Applies When

An ordinary withdrawal or unspecified Bitcoin transaction is pending; CPFP is confused with replacement; local resync is mistaken for network cancellation.

## Protocol validation and explorer evidence

Bisq performs transaction and protocol validation; it is incorrect to say it relies on no checks beyond a manual explorer search. An explorer can help inspect a transaction and whether an output has been spent, but merely finding the transaction or matching its outputs is not a complete proof that the proposed deposit is valid. For a validation error, preserve the exact task, transaction IDs and version for support. This record does not establish a separate universal validate-input button or a promised Bisq 2 library replacement.

## Evidence / Sources

- [Deposit transaction pending in mempool and CPFP](https://bisq.wiki/Deposit_transaction_pending_in_mempool_and_CPFP)
- [Resyncing SPV file](https://bisq.wiki/Resyncing_SPV_file)
- [Support Agent Knowledge Base](https://bisq.wiki/Support_Agent_Knowledge_Base)

- https://bisq.wiki/Wallet
- https://bisq.wiki/Import_Bisq_wallet_as_watch_only_wallet_in_Sparrow
- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/core/src/main/java/bisq/core/trade/validation/DepositTxValidation.java

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 452, 1067, 1180, 1364, 1888, 2279. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

---
id: bisq1-failed-trade-fees
title: Bisq 1 failed trades and fee reimbursement
type: llm_wiki
page_type: support_playbook
status: proposed
protocol: multisig_v1
reviewed_by: null
reviewed_at: null
risk_level: high
source_refs:
  - wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees
  - wiki:Deposit transaction
  - wiki:Mediation
  - wiki:Resyncing SPV file
  - wiki:Troubleshooting wallet issues
  - wiki:Fee Reimbursement Agent
  - wiki:BuyerVerifiesPreparedDelayedPayoutTx Exception error
---
## Canonical Support Answer

A Bisq 1 failed trade is primarily about whether the maker fee transaction, taker fee transaction, and deposit transaction actually exist and are confirmed on-chain. If there is no valid deposit transaction, the trade amount and security deposits were not locked in multisig, so the user's possible loss is normally limited to trade fees and miner fees.

The practical support path is to inspect the trade details, copy the maker fee txid, taker fee txid, and deposit txid if present, and verify each on a Bitcoin block explorer. If the deposit txid is missing, `N/A`, invalid, or not found on-chain, treat it as a failed trade. Perform an SPV resync if Bisq's wallet state appears stale, then move the trade to failed when the UI offers that path. If the deposit transaction is confirmed on-chain but Bisq is not recognizing it, use the confirmed-deposit-stuck page instead.

A failed trade does not refund the trade amount or security deposit because those funds were never locked by a valid deposit transaction. If the UI balance does not reflect that, the likely issue is stale wallet state; use SPV resync and verify wallet UTXOs before concluding funds are missing.

Reimbursement is considered only for significant lost trade fees or miner fees, not for funds that never left the wallet. If the amount is meaningful, use the documented fee-reimbursement path and include screenshots plus maker/taker/deposit transaction details. Do not promise reimbursement before the loss and policy are verified.

Errors such as `BuyerVerifiesPreparedDelayedPayoutTx` can be related to peers constructing different delayed payout transactions, often because of DAO-state inconsistency. First verify whether a deposit transaction exists. If no valid deposit transaction exists, keep it in the failed-trade workflow; if DAO state is also involved, check DAO consensus and use the DAO/DPT page for that part of the diagnosis.

## Applies When

- The user reports maker/taker/deposit transaction failures.
- The user says maker fee or taker fee is confirmed but the deposit transaction fails or is missing.
- The deposit txid is missing, `N/A`, invalid, or not found on a block explorer.
- The user sees a market-price tolerance, timeout, DAO-state, or delayed-payout setup error and no valid deposit transaction exists.
- The user asks what happened to the trade amount or security deposit after a failed trade.
- The user asks whether failed-trade fees can be reimbursed.
- The user asks what to check when a failed trade appears in one or both peers' clients.

## Do Not Say

- Do not say all failed trades imply lost trade amount or security deposit.
- Do not promise reimbursement for small or unverified fee losses.
- Do not skip transaction-id verification.
- Do not recommend CPFP unless there is a real unconfirmed on-chain transaction to accelerate.
- Do not route this as a Bisq Easy mediation/reject flow when the question contains Bisq 1-only fee/deposit transaction language.
- Do not tell users to manually delete local trade database files as the first recovery step.
- Do not say a deposit-confirmed trade has failed until the txid has actually been checked.

## Evidence / Sources

- `wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees` explains common failure modes, SPV resync, and reimbursement criteria.
- `wiki:Deposit transaction` explains how to locate and verify the deposit transaction.
- `wiki:Mediation` states mediators check maker fee, taker fee, and deposit transaction IDs.
- `wiki:Resyncing SPV file` and `wiki:Troubleshooting wallet issues` document stale wallet-state recovery.
- `wiki:Fee Reimbursement Agent` documents the fee reimbursement role and issue-template evidence.
- `wiki:BuyerVerifiesPreparedDelayedPayoutTx Exception error` documents DPT mismatch and DAO-state context.

## Review Notes

- Fee-loss thresholds and DAO reimbursement policy should be rechecked if policy changes.
- Production candidates about payment-method disputes, privacy risk, Wise/Zelle scam risk, and general security-deposit behavior were not absorbed here unless they affected failed-trade diagnosis.

## Last Change Summary

Curated failed-trade production candidates into one clear decision tree: verify txids, separate missing deposit from confirmed deposit, explain why trade/security-deposit funds are normally not lost, and limit reimbursement guidance to verified fee losses.

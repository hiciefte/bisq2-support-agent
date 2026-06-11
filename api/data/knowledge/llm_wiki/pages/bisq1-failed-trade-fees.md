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
---
## Canonical Support Answer

A Bisq 1 failed trade is usually about whether the maker/taker fee transaction and deposit transaction actually exist and confirmed. If there is no valid deposit transaction, the trade amount and security deposit were not locked in multisig, so the user's possible loss is normally limited to trade fees and miner fees.

The practical support path is to inspect the maker fee txid, taker fee txid, and deposit txid from the trade details, then check whether they are valid on-chain. If the maker fee is confirmed but the deposit transaction is missing, invalid, or absent from the blockchain after a market-price tolerance or protocol error, treat it as a Bisq 1 failed-trade state: move or leave it in the failed-trades workflow, reconcile wallet state with an SPV resync when needed, and retry only with a fresh healthy offer.

Reimbursement is considered only for significant lost fees, not for funds that never left the wallet because the deposit transaction never happened. If the situation is unclear, collect the trade ID, maker/taker fee txids, deposit txid if present, and logs for support/mediation instead of guessing or recommending CPFP for a transaction that does not exist.

## Applies When

- The user reports maker/taker/deposit transaction failures.
- The user says maker fee is confirmed but the deposit transaction fails or is missing.
- The user sees missing or invalid deposit txids.
- The user reports a market-price tolerance or protocol error and no valid deposit transaction.
- The user asks what to do when a trade fails with no valid deposit transaction.
- The user asks whether failed-trade fees can be reimbursed.
- The user asks what to check when a failed trade appears in both peers' clients.

## Do Not Say

- Do not say all failed trades imply lost trade amount or security deposit.
- Do not promise reimbursement for small or unverified fee losses.
- Do not skip transaction-id verification.
- Do not recommend CPFP unless there is a real unconfirmed on-chain transaction to accelerate.
- Do not route this as a Bisq Easy mediation/reject flow when the question contains Bisq 1-only fee/deposit transaction language.

## Evidence / Sources

- `wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees` explains common failure modes, SPV resync, and reimbursement criteria.
- `wiki:Deposit transaction` explains how to locate and verify the deposit transaction.
- `wiki:Mediation` states mediators check maker fee, taker fee, and deposit transaction IDs.

## Review Notes

- Fee-loss thresholds and DAO reimbursement policy should be rechecked if policy changes.

## Last Change Summary

Converted from generated support playbook into internal LLM Wiki page; ready for local support-admin review.

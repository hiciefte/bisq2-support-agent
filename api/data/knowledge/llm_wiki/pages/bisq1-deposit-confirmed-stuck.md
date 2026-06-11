---
id: bisq1-deposit-confirmed-stuck
title: Bisq 1 deposit confirmed but trade appears stuck
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: codex-initial-llm-wiki-review
reviewed_at: "2026-05-13"
risk_level: high
source_refs:
  - wiki:Deposit transaction
  - wiki:Dispute Resolution in Bisq 1
  - wiki:Mediation
  - wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees
  - wiki:Resyncing SPV file
  - wiki:Troubleshooting wallet issues
---
## Canonical Support Answer

When a Bisq 1 deposit transaction is confirmed on-chain but the trade UI appears stuck, separate blockchain state from application/protocol state. First verify the deposit txid from the trade details on a block explorer.

If the symptom looks like wallet-chain inconsistency, such as incorrect balance, missing transaction display, or stale wallet state, have the user perform an SPV resync from the Bisq interface and restart as prompted. After the resync, re-check the trade state and trade details.

If payment details are still missing, payment was sent, funds may be locked, or the trade protocol is still not progressing after basic wallet sync checks, keep the trade open and use trader chat or mediation rather than deleting data or attempting manual recovery alone. The mediator can ask both parties for proof and transaction details and can determine whether the issue is a UI sync problem, peer communication problem, or protocol failure.

If the deposit transaction is not valid or missing, treat it as a failed-trade case instead of a stuck confirmed-deposit case.

## Applies When

- The user says deposit is confirmed but Bisq still shows the trade stuck.
- Payment details or peer actions do not appear after deposit confirmation.
- The user needs to distinguish SPV wallet resync from DAO-state resync.
- The user asks whether they should delete or cancel a stuck trade.

## Do Not Say

- Do not tell the user to delete local trade data as a first step.
- Do not treat a missing deposit txid and confirmed deposit txid as the same problem.
- Do not suggest DAO-state rebuild for a normal wallet-chain display issue unless the error is DAO/DPT-specific.
- Do not bypass mediation when funds may be locked in multisig.

## Evidence / Sources

- `wiki:Deposit transaction` explains locating and verifying the deposit txid.
- `wiki:Dispute Resolution in Bisq 1` describes trader chat and mediation paths.
- `wiki:Mediation` documents mediator transaction checks and proof requests.
- `wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees` distinguishes failed/missing deposit transactions from valid deposits.
- `wiki:Resyncing SPV file` and `wiki:Troubleshooting wallet issues` document SPV resync for missing transactions, incorrect balances, and stale wallet-chain state.

## Review Notes

- Exact UI labels vary by Bisq 1 version; verify before giving click-by-click instructions.

## Last Change Summary

Added SPV-resync-first guidance for wallet-chain display issues while preserving mediation for locked-funds or missing-peer-data cases.

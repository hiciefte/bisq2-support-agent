---
id: bisq1-offer-fee-tx-not-found
title: Bisq 1 offer deactivated because fee transaction was not found
type: llm_wiki
page_type: support_playbook
status: proposed
protocol: multisig_v1
reviewed_by: null
reviewed_at: null
risk_level: medium
source_refs:
  - wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees
  - wiki:Trading fees
  - wiki:Paying trading fees with BSQ
---
## Canonical Support Answer

When Bisq 1 deactivates an offer because a BTC fee transaction was not found, treat it as a fee/transaction-state problem before treating it as a dispute. The maker fee transaction is part of publishing an offer. If the BTC fee transaction did not confirm, cannot be found on-chain, or the wallet is out of sync, the offer can become invalid or fail to propagate correctly.

The safe recovery path is: confirm which fee-payment mode was selected, inspect the maker fee transaction ID if one exists, verify whether it appears on-chain, and consider an SPV resync if the wallet state is stale. If actual fees were lost and the amount is significant, the reimbursement path may be considered under the failed-trade fee policy.

## Applies When

- The user sees offer deactivated because BTC fee transaction was not found.
- The user asks what "offer deactivated because BTC fee transaction not found" means.
- The user asks how to recover after the BTC fee transaction for an offer cannot be found.
- Maker fee is shown in the app but the offer is not valid or not visible.
- The user asks whether fees are lost after offer creation failure.

## Do Not Say

- Do not say the trade amount was lost when only the fee transaction is missing.
- Do not promise reimbursement before verifying fee loss and amount.
- Do not ignore whether fees were paid in BTC or BSQ.
- Do not describe this as a completed trade dispute unless a trade/deposit transaction actually exists.

## Evidence / Sources

- `wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees` explains maker/taker txid checks, out-of-sync wallets, SPV resync, and fee reimbursement criteria.
- `wiki:Trading fees` explains maker/taker fees and BTC/BSQ fee mode.
- `wiki:Paying trading fees with BSQ` explains fee-selection behavior.

## Review Notes

- Exact UI wording should be checked against the user's Bisq 1 version.

## Last Change Summary

Converted from generated support playbook into internal LLM Wiki page; ready for local support-admin review.

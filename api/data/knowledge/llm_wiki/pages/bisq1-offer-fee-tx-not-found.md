---
id: bisq1-offer-fee-tx-not-found
title: Bisq 1 offer deactivated because fee transaction was not found
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: suddenwhipvapor
reviewed_at: '2026-06-27'
risk_level: medium
source_refs:
- wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees
- wiki:Trading fees
- wiki:Paying trading fees with BSQ
- wiki:Resyncing SPV file
- wiki:Troubleshooting wallet issues
- wiki:Account limits
- wiki:Payment account age witness
- faq:1117
---
## Canonical Support Answer

When Bisq 1 deactivates an offer because a BTC fee transaction was not found, treat it as a fee/transaction-state problem before treating it as a dispute. The maker fee transaction is part of publishing an offer. If the BTC fee transaction did not confirm, cannot be found on-chain, or the wallet is out of sync, the offer can become invalid or fail to propagate.

The safe recovery path is:
- look for the maker fee transaction id on a blockchain explorer, to verify it exists and is confirmed
- if the maker fee transaction exists but it is not confirmed, the offer will be automatically disabled until the transaction is mined into a block
- if the maker fee transaction does not exist, the offer is invalid and should be deleted, no funds were lost because no fee was actually paid, and an SPV resync is needed to fix the wallet state
- if the maker fee transaction is confirmed in a block, but the offer still gets automatically disabled, it might be a UI issue that is usually resolved by manually enabling the offer, and closing and restarting Bisq

If actual fees were lost due to an issue with Bisq, rather than a mistake by the user (for example, deleting the offer, or spending the reserved balance) and the amount is significant, the reimbursement path may be considered under the failed-trade fee policy. Do not promise reimbursement before verifying fee loss, amount, and current policy.

Not every invisible or untaken offer is a missing-fee problem. Offer visibility can also be affected by account limits, account signing, payment-method constraints, version/network issues, or the taker having previously ignored, or been previously ignored by, the maker. If the warning is not specifically about a missing fee transaction, use the relevant account-limit, network, or payment-method page instead.

## Applies When

- The user sees offer deactivated because BTC fee transaction was not found.
- The user asks what `offer deactivated because BTC fee transaction not found` means.
- The user asks how to recover after the BTC fee transaction for an offer cannot be found.
- Maker fee transaction id is shown in the app but the offer is not valid or not visible.
- The user asks whether fees are lost after offer creation failure.
- The user asks why an offer disappeared and the exact message mentions missing maker fee transaction.

## Do Not Say

- Do not say the trade amount was lost when only the fee transaction is missing.
- Do not promise reimbursement before verifying fee loss and amount.
- Do not ignore whether fees were paid in BTC or BSQ.
- Do not describe this as a completed trade dispute unless a trade/deposit transaction actually exists.
- Do not diagnose every invisible offer as missing maker fee; first verify the exact warning and account-limit context.

## Evidence / Sources

- `wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees` explains maker/taker txid checks, out-of-sync wallets, SPV resync, and fee reimbursement criteria.
- `wiki:Trading fees` explains maker/taker fees and BTC/BSQ fee mode.
- `wiki:Paying trading fees with BSQ` explains fee-selection behavior.
- `wiki:Resyncing SPV file` and `wiki:Troubleshooting wallet issues` document stale wallet-state recovery.
- `wiki:Account limits`, `wiki:Payment account age witness`, and `faq:1117` document signing/limit context that can affect who can take offers.

## Review Notes

- Exact UI wording should be checked against the user's Bisq 1 version.
- Production candidates about confirmed deposits, locked payouts, BSQ wallet hygiene, and generic invisible offers were intentionally not all absorbed as missing-fee cases.

## Last Change Summary

Tightened offer-fee troubleshooting by distinguishing missing maker-fee transactions from account-limit, network, wallet, and generic offer-visibility issues.

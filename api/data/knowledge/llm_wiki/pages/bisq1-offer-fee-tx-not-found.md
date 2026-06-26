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
  - wiki:Resyncing SPV file
  - wiki:Troubleshooting wallet issues
  - wiki:Account limits
  - wiki:Payment account age witness
  - faq:1117
---
## Canonical Support Answer

When Bisq 1 deactivates an offer because a BTC fee transaction was not found, treat it as a fee/transaction-state problem before treating it as a dispute. The maker fee transaction is part of publishing an offer. If the BTC fee transaction did not confirm, cannot be found on-chain, or the wallet is out of sync, the offer can become invalid or fail to propagate correctly.

The safe recovery path is: confirm the exact deactivation message, confirm which fee-payment mode was selected, inspect the maker fee transaction ID if one exists, and verify whether it appears on-chain. If wallet state is stale or Bisq cannot see a transaction that exists, perform an SPV resync. If the offer is invalid or missing because the fee transaction never existed, delete/recreate the offer only after accepting that the original maker fee may be lost.

If actual fees were lost and the amount is significant, the reimbursement path may be considered under the failed-trade fee policy. Do not promise reimbursement before verifying fee loss, amount, and current policy.

Not every invisible or untaken offer is a missing-fee problem. Offer visibility can also be affected by account limits, account signing, payment-method constraints, version/network issues, or the taker's eligibility. If the warning is not specifically about a missing fee transaction, use the relevant account-limit, network, or payment-method page instead.

## Applies When

- The user sees offer deactivated because BTC fee transaction was not found.
- The user asks what `offer deactivated because BTC fee transaction not found` means.
- The user asks how to recover after the BTC fee transaction for an offer cannot be found.
- Maker fee is shown in the app but the offer is not valid or not visible.
- The user asks whether fees are lost after offer creation failure.
- The user asks why an offer disappeared and the exact message mentions missing maker/fee transaction.

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

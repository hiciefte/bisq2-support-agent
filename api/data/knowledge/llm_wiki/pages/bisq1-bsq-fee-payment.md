---
id: bisq1-bsq-fee-payment
title: Bisq 1 BSQ balances and trading-fee payment
type: llm_wiki
page_type: support_playbook
status: proposed
protocol: multisig_v1
reviewed_by: null
reviewed_at: null
risk_level: medium
source_refs:
  - wiki:Paying trading fees with BSQ
  - wiki:Trading fees
---
## Canonical Support Answer

Bisq 1 can pay trading fees in BTC or BSQ. BSQ is a colored bitcoin token kept in the Bisq BSQ wallet, separate from the plain BTC wallet. The user chooses BTC or BSQ fee payment on the make-offer or take-offer confirmation screen.

If a user believes they have enough BSQ but fee payment fails, support should first verify that the BSQ is actually available in the Bisq BSQ wallet and that the user selected BSQ as the fee-payment option. The user may also need enough BTC/miner-fee capacity for the transaction flow, depending on the action.

Keep the answer conservative: explain the fee-selection model and ask for exact error text/screenshots/logs if the balance appears sufficient but payment fails.

## Applies When

- The user asks why BSQ fee payment failed.
- The user asks how to pay Bisq 1 trading fees with BSQ.
- The user sees a sufficient-looking BSQ balance but cannot start a trade.

## Do Not Say

- Do not treat BSQ as the same wallet balance as BTC.
- Do not guarantee the displayed balance is spendable without checking exact context.
- Do not recommend sending BSQ to a normal BTC address.

## Evidence / Sources

- `wiki:Paying trading fees with BSQ` explains the separate BSQ wallet and fee selection.
- `wiki:Trading fees` explains BTC vs BSQ fee rates and that the user chooses the payment mode.

## Review Notes

- Exact current fee rates are DAO parameters and should be checked live when needed.

## Last Change Summary

Converted from generated support playbook into internal LLM Wiki page; ready for local support-admin review.

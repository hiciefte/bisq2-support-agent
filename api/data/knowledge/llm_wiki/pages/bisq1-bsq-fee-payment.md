---
id: bisq1-bsq-fee-payment
title: Bisq 1 BSQ balances, swaps, and trading-fee payment
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: suddenwhipvapor
reviewed_at: '2026-06-27'
risk_level: medium
source_refs:
- wiki:BSQ
- wiki:Trading BSQ
- wiki:How to sell BSQ on Bisq
- wiki:Paying trading fees with BSQ
- wiki:Trading fees
- wiki:DAO technical overview
- wiki:Emergency wallet
- faq:1162
- faq:1166
---
## Canonical Support Answer

BSQ is Bisq's DAO token implemented as colored bitcoin, and BSQ transactions appear as normal transactions on the Bitcoin blockchain. It is recognized as BSQ by Bisq software and should be handled through Bisq's DAO/BSQ wallet exclusively. It is not the same balance as plain BTC and should not be sent to and from external BTC wallets.

Bisq 1 traders can pay trading fees in BTC or BSQ. The user chooses the fee-payment mode on the make-offer or take-offer confirmation screen. Paying fees with BSQ can provide a discount, but the BSQ must be available in the Bisq BSQ wallet and the transaction must also satisfy current Bitcoin/BSQ dust and change-output constraints.

If a user believes they have enough BSQ but fee payment fails, first verify that the BSQ is actually visible under DAO/BSQ wallet, that the user selected BSQ as the fee-payment option, and that the amount can be spent without violating dust/change constraints. Do not assume the balance shown in a generic wallet-info screen is the spendable BSQ amount.

To buy or sell BSQ for BTC, use the BSQ/BTC swap flow in Bisq 1. BSQ swaps are atomic; they are distinct from ordinary fiat trades and from using BSQ as a trading-fee payment token. If the user asks whether BSQ can buy anything on Bisq, answer narrowly: BSQ is used for DAO/governance functions, BSQ/BTC swaps, and optionally paying Bisq trading fees; normal BTC/fiat trades do not treat BSQ as a currency.

If BSQ or BTC wallet state appears wrong, use wallet verification and SPV/DAO-state troubleshooting as appropriate. Keep fee-payment support conservative: ask for exact error text/screenshots/logs when a balance appears sufficient but the transaction fails.

## Applies When

- The user asks what BSQ is or which blockchain it exists on.
- The user asks how to buy, sell, swap, receive, or transfer BSQ in Bisq 1.
- The user asks how to pay Bisq 1 trading fees with BSQ.
- The user sees a sufficient-looking BSQ balance but cannot start a trade or pay the fee.
- The user sees an insufficient-BSQ, BSQ dust, or BSQ wallet-balance problem.
- The user asks whether BSQ can be used to buy arbitrary assets on Bisq.

## Do Not Say

- Do not treat BSQ as the same wallet balance as BTC.
- Do not guarantee the displayed balance is spendable without checking exact context.
- Do not recommend sending BSQ to a normal external BTC wallet.
- Do not conflate BSQ/BTC swaps with ordinary fiat trades.
- Do not use this page for missing deposit transactions, stuck trades, security deposits, or mediation questions unless the question is specifically about BSQ fee payment.

## Evidence / Sources

- `wiki:BSQ` explains BSQ as colored bitcoin recognized by Bisq and stored/handled in Bisq software.
- `wiki:Trading BSQ` and `wiki:How to sell BSQ on Bisq` document BSQ/BTC swap behavior.
- `wiki:Paying trading fees with BSQ` explains the separate BSQ wallet, fee selection, and BSQ fee-payment constraints.
- `wiki:Trading fees` explains BTC vs BSQ fee rates and fee mode; exact fee, discount, and dust/change values should be checked against current Bisq/DAO parameters before quoting them.
- `wiki:DAO technical overview` provides DAO/BSQ context.
- `wiki:Emergency wallet` documents last-resort BSQ wallet recovery shortcuts.
- `faq:1162` and `faq:1166` cover receiving/checking BSQ in Bisq support answers.

## Review Notes

- Exact current fee rates, discount, and dust thresholds are DAO/protocol parameters and should be checked live when needed.
- Production candidates about failed trades, escrow, security deposits, mediation, and Windows external-wallet popups were intentionally not absorbed into this BSQ fee page.

## Last Change Summary

Clarified BSQ fee-payment spendability and dust/change-threshold handling without hard-coding an unverified evergreen value.

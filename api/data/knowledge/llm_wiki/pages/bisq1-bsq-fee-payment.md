---
id: bisq1-bsq-fee-payment
title: Bisq 1 BSQ balances and ordinary trading-fee payment
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: medium
source_refs:
- wiki:BSQ
- wiki:Trading BSQ
- wiki:Paying trading fees with BSQ
- wiki:Trading fees
- wiki:DAO technical overview
- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/core/src/main/java/bisq/core/btc/wallet/BsqCoinSelector.java#L77-L80
- https://bisq.wiki/DAO_technical_overview
---
## BSQ and BTC are different balances

BSQ is colored bitcoin interpreted by Bisq's DAO rules. It uses Bitcoin transactions but is not interchangeable with plain BTC. Receive it at `DAO > BSQ Wallet > Receive` and send through the BSQ-aware Bisq wallet. A generic Bitcoin wallet can spend the underlying sats without preserving BSQ coloring. Do not use an external BTC wallet as a shortcut to move BSQ.

For ordinary BSQ transfers, retain BTC for mining fees before withdrawing remaining BTC. When moving between Bisq installations, preserve both directories and verify the recipient BSQ address. This ordinary transfer rule must not be confused with the different input/output structure of an atomic BSQ swap.

## Paying ordinary trade fees

For Bisq 1 conventional trades, select BTC or BSQ for the trading fee in the make/take-offer flow. BSQ payment can provide a discount; consult the current displayed amounts and official fee documentation rather than promising a permanent percentage. Maker and taker trading fees differ; making an offer can cost less than taking one. Waiting longer for confirmation is not a trading-fee discount.

If a sufficient-looking balance cannot pay the fee, check the actual BSQ wallet, selected fee mode, transaction confirmations and exact validation message. Total displayed BSQ may not all be spendable: inputs, change and output constraints matter. Do not confuse a minimum trading fee with a dust threshold or require a universal fixed residual BSQ balance. Ask support for the exact version/error when constraints are unclear.

The BSQ amount burned for trading fees is distinct from constraints on the transaction’s inputs and remaining colored outputs. The inspected selector references 546 satoshis (5.46 BSQ), not the historical 516-satoshi example. This is not a universal instruction to buy that amount or retain a fixed residual balance: the actual error and output/change construction determine the remedy.

## Negative, unavailable or unconfirmed BSQ

Check local DAO consensus under `DAO > Network Monitor` and the relevant transactions/progress under `DAO > BSQ Wallet > Transactions`. Verify their Bitcoin network status independently. DAO recognition and SPV wallet tracking are distinct. If local DAO state is inconsistent, follow the documented DAO rebuild; if it is consistent but a balance remains wrong, provide the particular transaction evidence instead of repeating resets blindly.

An unconfirmed transaction can tie up inputs or change. Another confirmed output may allow other activity, but adding BSQ does not repair an invalid or never-broadcast transaction. Do not delete wallet/DAO files or consolidate blindly. Preserve backups, especially after restoring an older directory.

## Uses and market price

BSQ supports DAO functions and ordinary trading-fee payment, and can be exchanged for BTC in Bisq 1 atomic BSQ swaps. It is not a general balance for every fiat market. The price is negotiated by buyers and sellers; `Market` with BSQ selected shows market activity, not a guaranteed fixed redemption value. Acquisition by swap is one way to obtain BSQ, not the only way to receive it.

For swap account setup, input sufficiency, fees or timeouts, use `bisq1-bsq-swaps`. BSQ swaps are not conventional multisig fiat trades or Bisq Easy. Missing deposits and dispute release questions belong to their actual trade protocol.

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 696, 1174, 1899, 2360. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Evidence / Sources

- [BSQ](https://bisq.wiki/BSQ): official procedure or scope referenced above.
- [Trading BSQ](https://bisq.wiki/Trading_BSQ): official procedure or scope referenced above.
- [Paying trading fees with BSQ](https://bisq.wiki/Paying_trading_fees_with_BSQ): official procedure or scope referenced above.
- [Trading fees](https://bisq.wiki/Trading_fees): official procedure or scope referenced above.
- [DAO technical overview](https://bisq.wiki/DAO_technical_overview): official procedure or scope referenced above.

- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/core/src/main/java/bisq/core/btc/wallet/BsqCoinSelector.java#L77-L80

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

---
id: bisq1-offer-fee-tx-not-found
title: Bisq 1 offer deactivation and maker fee diagnosis
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: high
source_refs:
- https://bisq.wiki/Failed_Trades_-_Reimbursement_of_Trade_Fees_and_Miner_Fees
- https://bisq.wiki/Trading_fees
- https://bisq.wiki/Paying_trading_fees_with_BSQ
- https://bisq.wiki/Cloning_an_offer
- https://bisq.wiki/Account_limits
- https://github.com/bisq-network/bisq/blob/master/core/src/main/resources/i18n/displayStrings.properties
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/core/src/main/java/bisq/core/offer/bisq_v1/TriggerPriceService.java
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/core/src/main/java/bisq/core/provider/mempool/TxValidator.java
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/core/src/main/java/bisq/core/provider/mempool/TxValidator.java#L165
- https://bisq.wiki/DAO_technical_overview
---
## Canonical Support Answer

Read the exact offer warning and identify its maker fee transaction ID. Check whether that transaction exists and is confirmed. A genuinely pending fee can leave an offer unavailable until confirmation; a confirmed fee does not prove a trade deposit was created. Absence from one explorer is not proof of permanent invalidity, wallet corruption or zero fee loss.

If support verifies an invalid untaken offer, use the app's supported removal path. Back up before SPV resync when local wallet tracking is inconsistent. If the fee is confirmed but deactivation continues, preserve the error, fee mode and version for support; manual enable/restart may be tried but is not a guaranteed fix. A BSQ fee not recognized locally can require DAO-state investigation, which differs from BTC SPV resync. Total BSQ balance is not necessarily currently spendable.

For a verified confirmed-fee deactivation case, support may recommend Clone Offer and deactivating the original. Cloning shares the maker fee and reserved funds; duplicating incurs new fees. Follow the UI's clone constraints: an active same-method/currency original may prevent activating its clone. When one shared-fee offer is taken, related offers close because that funding is used. Do not assume confirmation itself causes deactivation.

Removing an untaken offer releases its reservation rather than generating an on-chain refund. Already spent maker/mining fees are not automatically refunded. If verified loss arose from a Bisq issue, consult the failed-trade fee policy; do not promise reimbursement for ordinary user cancellation.

Not every invisible offer is a fee problem. Check filters, account limits/signing, payment-method compatibility, network/version state and ignored peers. If an offer says already taken, inspect current alternatives without confirming an unwanted expensive trade just to test availability. Review price and total before any real commitment. Do not diagnose every such symptom as DAO divergence.

## Applies When

An offer repeatedly disables, a maker fee cannot be found, confirmed fees still produce an unavailable offer, or a clone/visibility question arises before an active funded trade.

## Specific fee validation errors

A deactivation message summarizing mempool validation is not the underlying diagnosis. Read the accompanying validation reason and fee transaction ID. A separate stuck payout is a different transaction and must be checked independently.

For the error “not a known BTC fee receiver,” the validator did not recognize the receiver of the fee transaction’s first output as an allowed BTC fee receiver. Preserve the exact message, fee transaction ID and version, and have support compare the transaction with the receiver information used by the app. Check DAO synchronization if the accompanying evidence indicates it, but do not assume this message alone proves a DAO problem, a low mining fee or a missing transaction. Do not bypass validation or pay the fee again to force progress.

## Evidence / Sources

- [Failed Trades - Reimbursement of Trade Fees and Miner Fees](https://bisq.wiki/Failed_Trades_-_Reimbursement_of_Trade_Fees_and_Miner_Fees)
- [Trading fees](https://bisq.wiki/Trading_fees)
- [Paying trading fees with BSQ](https://bisq.wiki/Paying_trading_fees_with_BSQ)
- [Cloning an offer](https://bisq.wiki/Cloning_an_offer)
- [Account limits](https://bisq.wiki/Account_limits)
- [displayStrings.properties](https://github.com/bisq-network/bisq/blob/master/core/src/main/resources/i18n/displayStrings.properties)

- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/core/src/main/java/bisq/core/offer/bisq_v1/TriggerPriceService.java
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/core/src/main/java/bisq/core/provider/mempool/TxValidator.java
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/core/src/main/java/bisq/core/provider/mempool/TxValidator.java#L165
- https://bisq.wiki/DAO_technical_overview

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 389, 1938, 2352. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

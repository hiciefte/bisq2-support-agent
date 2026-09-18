---
id: bisq1-failed-trade-fees
title: Bisq 1 failed trade diagnosis and verified fee losses
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-batch-20260918
reviewed_at: '2026-09-18T08:30:52.377693+00:00'
risk_level: high
source_refs:
- https://bisq.wiki/Failed_Trades_-_Reimbursement_of_Trade_Fees_and_Miner_Fees
- https://bisq.wiki/Deposit_transaction
- https://bisq.wiki/Resyncing_SPV_file
- https://bisq.wiki/BuyerVerifiesPreparedDelayedPayoutTx_Exception_error
- https://bisq.wiki/Making_a_reimbursement_request
---
## Canonical Support Answer

A genuinely failed setup with no valid deposit is different from a pending deposit, confirmed escrow, or a missing payout. Read the exact error and identify maker fee, taker fee and deposit transaction IDs separately. Check each actual ID and its inputs/confirmation state; an absent ID cannot be searched. N/A, empty details, zero peers, a price-tolerance timeout or a local Failed label warrants investigation, not an automatic conclusion from one explorer miss.

### Establish what happened

A maker/taker fee failure or delayed-payout construction disagreement can prevent a valid deposit. Valid fee transactions with no deposit can suggest a later setup problem, including DAO disagreement, but do not establish blame. A replaced maker fee may invalidate dependent transactions while a taker fee has already confirmed. Preserve exact errors such as BuyerVerifiesPreparedDelayedPayoutTx and lock-time mismatch, installed version and relevant logs for support; check DAO consensus only where indicated. Rebuilding your state does not fix the peer's state automatically.

If the actual deposit is confirmed, use the confirmed-deposit or dispute workflow even when the UI says Failed. If genuinely pending, use the pending-deposit workflow. Mempool eviction is not invalidation, and elapsed time does not prove a permanently failed trade. Do not create a replacement deposit, manually broadcast a bundle of guessed transactions, or retry paid trades to gather examples.

### Reserved balance versus spent fees

If the intended outputs were never spent into a valid deposit, there is no on-chain deposit refund to wait for. They may remain reserved locally or by a still-active offer. Inspect Funds > Available funds, Funds > Transactions and Open Offers, including clones sharing the reservation. Actual confirmed maker/taker and mining fees may still be spent. A failed setup does not imply zero fees, a lost trade amount, or automatic reimbursement.

Back up the data before the documented SPV resync when local tracking is stale. Once failure is established, use the application's Move to Failed action when offered and restart if prompted. This changes local handling; it does not cancel network transactions or unlock an existing multisig. If the action is absent, details are empty or balances remain wrong after completed resync, contact verified support with evidence. Do not delete PendingTrades or other databases to force the balance to change.

### Payment already sent or old incomplete trades

If fiat/altcoins were already paid before a deposit failure was understood, tell support immediately and preserve payment proof. No valid escrow means the normal BTC payout path may not exist; no bank refund is guaranteed. An expired timer, old ticket or missing local trade does not settle ownership. Inspect history, balances and the deposit before choosing recovery.

### Fee reimbursement

Request only verified eligible fee losses under the official failed-trade reimbursement policy. Follow its current support-repository issue/template route, providing the requested maker/taker/deposit evidence and screenshots while removing sensitive payment details. Publication/cancellation of an untaken offer and user-caused fee loss are not automatically reimbursable. Do not promise a fixed threshold or approval. A DAO reimbursement for an unresolved arbitrated trade is a separate process described on the dispute page.

## Applies When

Missing/invalid deposit, failed setup, fee loss, stale reserved balance or missing Move to Failed. A confirmed deposit needs the funded-trade branch instead.


## Evidence / Sources

- [Failed Trades - Reimbursement of Trade Fees and Miner Fees](https://bisq.wiki/Failed_Trades_-_Reimbursement_of_Trade_Fees_and_Miner_Fees)
- [Deposit transaction](https://bisq.wiki/Deposit_transaction)
- [Resyncing SPV file](https://bisq.wiki/Resyncing_SPV_file)
- [BuyerVerifiesPreparedDelayedPayoutTx Exception error](https://bisq.wiki/BuyerVerifiesPreparedDelayedPayoutTx_Exception_error)
- [Making a reimbursement request](https://bisq.wiki/Making_a_reimbursement_request)

## Review Notes

Independently reviewed by the parent AI reviewer. Preserve private case evidence outside this reusable page.

## Last Change Summary

Preserved diagnostic and reimbursement guidance while removing guaranteed failure/refund from explorer absence and destructive recovery.

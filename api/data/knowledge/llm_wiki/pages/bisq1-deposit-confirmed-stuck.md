---
id: bisq1-deposit-confirmed-stuck
title: Bisq 1 deposit confirmation and pending transaction diagnosis
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-batch-20260918
reviewed_at: '2026-09-18T08:30:52.377693+00:00'
risk_level: high
source_refs:
- https://bisq.wiki/Deposit_transaction
- https://bisq.wiki/Resyncing_SPV_file
- https://bisq.wiki/Backing_up_application_data
- https://bisq.wiki/Deposit_transaction_pending_in_mempool_and_CPFP
- https://bisq.wiki/Dispute_Resolution_in_Bisq_1
---
## Canonical Support Answer

Identify the actual deposit transaction before choosing a remedy. Open the trade's information icon in Open Trades or History and locate the deposit transaction ID; Funds > Transactions may help if trade details are incomplete. A trade ID, funding address, maker fee and taker fee are not the deposit ID. Check the same transaction on a Bitcoin explorer; confirmation of a fee transaction does not prove deposit confirmation.

### Confirmed on-chain but stale in Bisq

Preserve a full data backup, then use Settings > Network Info > RESYNC SPV WALLET and complete the official guide's prompted restarts and synchronization. A normal restart is not a resync. Recheck the same deposit, trade state and wallet balance afterward. If completed resync attempts do not help, collect the exact error, version, transaction evidence and attempted steps for support rather than repeatedly resetting. A trade marked Failed can still contain a confirmed deposit and locked funds.

If payment details or buttons remain absent, or errors mention null deposit, unexpected input count or maker/taker inputs not matching the contract, preserve state and open the requested support ticket. Do not send fiat or altcoins while the contract or deposit is unresolved. If payment already occurred, say so explicitly; never pay again to fix the UI. If the app is unavailable during resync, notify the peer and verified support, preserve timing/screenshot evidence, and do not restore a seed into a new profile to finish the trade.

### Actually pending on the network

A valid unconfirmed deposit can remain pending for hours or days. Inspect its effective fee rate and unconfirmed ancestors, not just its absolute fee or individual fee rate. Low-fee external funding or a taker fee can hold up the deposit. ETA means estimated confirmation time; changing explorer estimates do not guarantee a deadline or prove a scam. The payment-period clock does not start until deposit confirmation. Waiting is an option, not an automatic penalty, cancellation or refund trigger.

SPV resync updates local tracking; it does not accelerate miners, clear the network mempool or cancel a transaction. A mediator cannot cancel an unconfirmed Bitcoin deposit. Even mutual cancellation needs support coordination and a verified transaction state; do not invalidate funding or send a replacement deposit yourself.

### Advanced CPFP boundaries

CPFP may help only when the relevant trader controls an eligible unconfirmed change output in the funding chain. It does not mean spending the locked 2-of-2 multisig deposit. Follow the official deposit-CPFP guide and calculate the combined package fee and cost; approximate multipliers are not universal instructions. External-funding CPFP may confirm its parent while an independently low-fee deposit still waits. Internally funded trades may have no suitable output. Do not send the full amount to a deposit address, repeat paid accelerations blindly or reveal wallet secrets. Waiting remains valid if the cost or procedure is unsuitable.

CPFP spends an output without rewriting its parent; it cannot redirect the original deposit. Replacement/RBF instead conflicts with original inputs and can invalidate trade dependencies. Bisq's trade wallet does not provide a routine RBF trade-cancellation flow. Do not turn speculative external-wallet replacement advice into a recovery recipe.

### Missing, conflicting or inconsistent evidence

One explorer not finding a transaction, or a node evicting it, does not prove it was never broadcast or cannot confirm later. If explorers disagree or report spent/invalid inputs, have support inspect the deposit and funding chain. Use the failed-trade page only after no valid deposit is established. DAO rebuild is for demonstrated DAO/DPT state problems, not ordinary SPV display mismatch. Never delete trade databases to force progress.

## Applies When

Deposit is pending, confirmed but unrecognized, or unclear after resync; CPFP/RBF questions concern an active Bisq 1 trade. A payout or delayed payout is a different transaction and needs its matching workflow.


## Evidence / Sources

- [Deposit transaction](https://bisq.wiki/Deposit_transaction)
- [Resyncing SPV file](https://bisq.wiki/Resyncing_SPV_file)
- [Backing up application data](https://bisq.wiki/Backing_up_application_data)
- [Deposit transaction pending in mempool and CPFP](https://bisq.wiki/Deposit_transaction_pending_in_mempool_and_CPFP)
- [Dispute Resolution in Bisq 1](https://bisq.wiki/Dispute_Resolution_in_Bisq_1)

## Review Notes

Independently reviewed by the parent AI reviewer. Preserve private case evidence outside this reusable page.

## Last Change Summary

Merged repeated confirmation cases; corrected eviction, SPV, fee acceleration and automatic-refund assumptions.

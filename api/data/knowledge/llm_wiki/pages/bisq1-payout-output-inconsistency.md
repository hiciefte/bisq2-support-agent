---
id: bisq1-payout-output-inconsistency
title: Bisq 1 missing payout and inconsistent completion state
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-batch-20260918
reviewed_at: '2026-09-18T08:30:52.377693+00:00'
risk_level: high
source_refs:
- https://bisq.wiki/Trade_payout_address_reuse_issue
- https://bisq.wiki/Support_Agent_Knowledge_Base
- https://bisq.wiki/Mediation
- https://bisq.wiki/Resyncing_SPV_file
---
## Canonical Support Answer

A Completed or History label does not prove this trade paid out. Check the actual payout transaction, expected amount/address, Funds > Transactions and the deposit's spent/unspent state on-chain. A fee transaction or old incoming payment is not evidence of the current payout. For disappearing balances, inspect outgoing transactions as well as the expected incoming payout before concluding funds remain locked or were stolen.

Normally the BTC seller signs and broadcasts the payout after verifying payment receipt; this role is independent of maker/taker. The buyer receives trade BTC plus their deposit and the seller receives their deposit, subject to fees. A documented address-reuse/output-state issue can cause premature local completion, including a buyer's trade moving to History while the seller still sees it open. Do not assume that bug without evidence or infer the seller can no longer complete normally.

If payment was received but SellerBroadcastPayoutTx or another confirmation error occurs, notify the peer and open the trade's support ticket. Give verified support the trade ID, deposit ID, payout ID if present, exact error and acceptance/payment state. If the trade no longer has chat, support can coordinate the peers through verified private contact. Preserve data; a coordinated manual recovery may be needed but is not promised.

A present unconfirmed payout is a network-confirmation problem; an absent payout requires determining whether it was constructed/broadcast and whether escrow remains unspent. A payout disappearing from one mempool is not cancellation or proof of failure. Do not apply an absent-deposit refund recipe, spend escrow outputs or delete trade files. SPV resync can repair a confirmed-on-chain/local-wallet mismatch but is not a substitute for diagnosing payout/signature problems.

## Applies When

Premature completed status, missing buyer payout, inconsistent peer trade states, output/address-reuse errors or failed seller payout broadcast.


## Evidence / Sources

- [Trade payout address reuse issue](https://bisq.wiki/Trade_payout_address_reuse_issue)
- [Support Agent Knowledge Base](https://bisq.wiki/Support_Agent_Knowledge_Base)
- [Mediation](https://bisq.wiki/Mediation)
- [Resyncing SPV file](https://bisq.wiki/Resyncing_SPV_file)

## Review Notes

Independently reviewed by the parent AI reviewer. Preserve private case evidence outside this reusable page.

## Last Change Summary

Retained transaction-first payout diagnosis and added seller broadcasting role and premature-History coordination.

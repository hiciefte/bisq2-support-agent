---
id: bisq1-dispute-mediation-arbitration
title: Bisq 1 mediation, arbitration and payment disputes
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: high
source_refs:
- https://bisq.wiki/Dispute_Resolution_in_Bisq_1
- https://bisq.wiki/Trading_rules
- https://bisq.wiki/Table_of_penalties
- https://bisq.wiki/Arbitration
- https://bisq.wiki/Finding_your_mediator
- https://bisq.wiki/Finding_your_arbitrator
- https://bisq.wiki/Making_a_reimbursement_request
- https://bisq.wiki/Dumping_delayed_payout_transactions
- https://bisq.wiki/Delayed_payout_transaction_pending_in_mempool_and_CPFP
- https://bisq.wiki/Burning_Men
- https://bisq.wiki/Frequently_asked_questions
- https://bisq.network/blog/bisq-v1-2-released/
- https://bisq.wiki/Deposit_transaction
---
## Canonical Support Answer

Bisq 1 uses trader chat, mediation and, when necessary, arbitration. Select the affected open trade and press Ctrl+O (Cmd+O on macOS) to request mediation, then use the ticket's chat in Support. You can request mediation before the payment deadline when there is a problem; a button also appears when the trade period expires. A Matrix support link is not the in-app ticket. For two affected trades, open a case for each. If the shortcut or ticket is unavailable, preserve the exact error and contact verified support rather than deleting trade files.

### Payment, deadlines and cancellation

Buyers should pay according to the agreed contract and app instructions. Sellers can confirm towards the end of the trade period, especially for new chargeback-risk accounts. Trader-chat replies are not mandatory; silence before the deadline alone does not establish fraud or late release. The payment period ending does not automatically cancel, refund, release BTC or remove access to mediation. If paid but unsettled, preserve proof and request mediation. If the seller claims nonreceipt, check recipient and bank/payment status: proof of initiating payment is not automatically proof of correct receipt. Do not send a duplicate payment.

If the buyer cannot pay, the bank rejects details, the account is restricted, the buyer proposes partial payment, or either party wants to cancel an accepted rate, explain the problem to the peer and mediator. An unfavorable accepted price is not a free cancellation right. Do not substitute a new account, Wise link, Pix key, Zelle method, gift-card region or other payment details merely on a chat request. Ask the mediator to assess any mutually proposed alternative. Material sender/account-holder mismatch calls for immediate mediation. Do not return money, confirm unreceived funds or accept a cancellation payout merely on a promised bank refund; ask the mediator how actual receipt/refund evidence affects the proposal.

Bank recalls affecting previous trades need prompt evidence-based review of pending trades and account identities; do not seize new funds as automatic compensation. XMR proof errors require distinguishing actual wallet receipt from missing payment: never confirm receipt just to bypass an invalid transaction-key message. If payment is verified but confirmation is blocked, report that exact distinction. Penalties depend on the rules, evidence and circumstances. Published penalty percentages are maxima based on the stated trade-value basis, not automatic percentages of the security deposit or amounts to add together. No fixed compensation, full-deposit forfeiture or penalty-free cancellation is guaranteed.

### Mediation proposals and communication problems

The mediator proposes a payout and has no third key to unilaterally spend the 2-of-2 multisig. Opening a dispute does not let the peer take your share. Both traders must participate in the mediated payout path. You can keep negotiating and tell the mediator your agreement, but a chat agreement does not itself update payout signatures. If an old proposal was already accepted and then revised, ask the mediator to coordinate the replacement with both traders; do not invent a reject/reset procedure or assume a new message replaces the old signature.

For SendMediatedPayoutSignatureMessage, Invalid state, payment-confirmation loops or missing payout after acceptance, check peer acceptance, message delivery and the actual payout transaction with support. Do not assume only fees are at stake or that resync alone resolves protocol state. Notify the peer when payment is already received but the UI cannot confirm. Follow the official Payment started troubleshooting guide for the exact symptom rather than paying again or deleting arbitrary Tor files.

Mediators and traders are expected to respond to dispute chat within 48 hours; this is not a guaranteed completion time. Notify the mediator of sync-related delays or planned absence and preserve evidence. Another verified agent may help an unavailable mediator, but coordinated recovery requires both peers. An N/A support-agent label does not prove automatic reassignment; use the trade information and official contact guides. An onion address is not a Matrix handle. Verify identities before sharing private trade evidence, and never share seeds or private keys. For future interactions, Settings > Preferences has an ignored-peers option using the peer's onion address; it does not cancel the current trade or replace its required communication.

### Arbitration and delayed payouts

When mediation cannot finish or its proposal is disputed, either trader can request arbitration once eligible. It is not buyer-only or automatic on rejection, silence or timer expiry. The delayed payout transaction (DPT) is prepared during setup and normally remains unpublished during a successful trade. Its block-based timelock is approximately 10 days for altcoin trades or 20 days for fiat trades from deposit confirmation, not from payment-period expiry. A disabled action needs the actual deposit-confirmation time and ticket state checked. The timelock is the earliest publication point, not a requirement to act that instant; separate reimbursement deadlines still matter.

Follow the in-app arbitration process. Publishing the eligible DPT spends the trade escrow to Burning Men recipients determined from DAO state; it does not send an automatic refund to the traders. Burning Men are not the refund agent deciding the case. The refund agent reviews evidence and provides any applicable payout from separate funds. Current compensation can depend on deposit settings and case circumstances; do not promise winner-takes-all, both deposits or unconditional BTC recovery. Refund-agent chat response expectations are up to five days, not a fixed settlement deadline. If neither party acts, the timelock alone does not publish the DPT or donate funds automatically.

A BTC arbitration payout is publicly linkable on-chain and the agent knows the case's supplied receiving address; do not promise anonymity or irrelevant coin history. If a DPT is confirmed but the UI disagrees, verify it is this trade's DPT rather than the deposit or normal payout and contact the assigned agent. Do not repeatedly publish or replace transactions to fix display state. A pending low-fee DPT is different from a pending deposit: a Burning Men recipient may be able to CPFP their own output after verified coordination and agreement on cost; traders must not apply the ordinary deposit recipe to funds they do not control.

For support-requested diagnostics, the official --dumpDelayedPayoutTxs=true startup option exports pending, failed and closed DPT JSON files under the application's data directory. Use the official OS-specific guide, preserve privacy, and distinguish --dumpStatistics=true. Exporting evidence is not authorization to broadcast. Manual DPT publication belongs to the verified eligible arbitration workflow, not generic trade recovery.

### Reimbursement and unresolved outcomes

First ask the mediator/agent to review a specific mistaken proposal with evidence. If escalation is needed, use the documented arbitration process; disagreement alone does not establish entitlement. A last-resort DAO reimbursement request has a public support-repository issue plus an in-app DAO Governance reimbursement proposal linking that issue. A forum/GitHub post alone does not put it to a DAO vote. Follow the current official eligibility, timing and proposal-phase instructions; preserve the DPT evidence and do not publish private payment-account data. Approval is not guaranteed. This differs from reimbursement of verified failed-trade mining/trading fees.

If no valid deposit was ever created, use failed-trade diagnosis rather than claiming funded escrow can be released. If payment occurred anyway, preserve both transaction and payment evidence and urgently explain this to support.

## Applies When

Payment cannot be made, receipt is disputed, paid BTC remains unreleased, a proposal cannot complete, agents are unreachable, arbitration eligibility is unclear, or reimbursement is requested.

## Older trades before the current escrow protocol

Identify each trade’s date, version and actual deposit/payout history before applying current arbitration instructions. Bisq changed from 2-of-3 to 2-of-2 escrow with version 1.2 in October 2019; an earlier trade need not have the current delayed-payout transaction. N/A alone does not prove funds are missing. Preserve the old data directory and inspect whether the deposit output was spent and where the payout went, with verified support if unclear. Do not construct or broadcast a delayed payout from a current guide merely to fill an old missing field.

## Evidence / Sources

- [Dispute Resolution in Bisq 1](https://bisq.wiki/Dispute_Resolution_in_Bisq_1)
- [Trading rules](https://bisq.wiki/Trading_rules)
- [Table of penalties](https://bisq.wiki/Table_of_penalties)
- [Arbitration](https://bisq.wiki/Arbitration)
- [Finding your mediator](https://bisq.wiki/Finding_your_mediator)
- [Finding your arbitrator](https://bisq.wiki/Finding_your_arbitrator)
- [Making a reimbursement request](https://bisq.wiki/Making_a_reimbursement_request)
- [Dumping delayed payout transactions](https://bisq.wiki/Dumping_delayed_payout_transactions)
- [Delayed payout transaction pending in mempool and CPFP](https://bisq.wiki/Delayed_payout_transaction_pending_in_mempool_and_CPFP)
- [Burning Men](https://bisq.wiki/Burning_Men)
- [Frequently asked questions](https://bisq.wiki/Frequently_asked_questions)

- https://bisq.network/blog/bisq-v1-2-released/
- https://bisq.wiki/Deposit_transaction

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 1462, 2128, 2395. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

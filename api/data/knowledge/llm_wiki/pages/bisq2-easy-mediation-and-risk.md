---
id: bisq2-easy-mediation-and-risk
title: Bisq Easy trade stages, mediation and payment risk
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: bisq_easy
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: high
source_refs:
- https://bisq.wiki/Bisq_Easy
- https://bisq.wiki/Dispute_Resolution_in_Bisq_2
- https://bisq.wiki/Reputation
- https://bisq.wiki/ACH
- https://bisq.wiki/Cash_by_Mail
- https://bisq.wiki/Dispute_resolution
- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/trade/src/main/java/bisq/trade/bisq_easy/protocol/messages/BisqEasyTakeOfferRequestHandler.java
- https://bisq.wiki/Bisq_Easy#Trade_rules
---
## Canonical Support Answer

Bisq Easy uses seller reputation rather than Bisq 1 multisig escrow or security deposits. The buyer pays first, irrespective of who created the offer. The seller verifies actual receipt before sending BTC. Reputation and an amount ceiling do not guarantee fulfillment, a refund or DAO compensation.

## Trade chat and cancellation boundary

Select the relevant trade under open trades and open its associated chat to exchange and check payment details. Exact controls vary by release. Keep the conversation and evidence in the trade context rather than moving negotiation to an unrelated private channel.

Before payment details are exchanged, either party can cancel without justification under the official Easy trade rules. After that exchange, failure to fulfill the agreement can breach the rules. Neither an unpaid status nor 24 hours or two days of silence creates an automatic consequence-free cancellation right. A buyer may still send a pending payment. Do not assume that an unresolved trade will close itself or that rejecting it refunds money.

## When the trade is delayed or the interface disagrees

Check the actual payment stage, agreed method and normal processing time. Ask the peer for an update. If the seller has already acknowledged receipt but BTC is absent, preserve that acknowledgment and request mediation. A named bot or historical operator incident does not create a guaranteed release deadline or excuse an indefinite delay.

Mediation is available from the Easy trade screen without a universal extra waiting period. If the control is missing, disabled or fails, contact established support with the version and error. Do not substitute the Bisq 1 Ctrl+O shortcut: that shortcut is documented for selecting a Bisq 1 open trade, not established here as an Easy command.

If peers see different payment stages, verify receipt in the bank/payment service and check any BTC transaction before sending again. A status mismatch is not a reason for Bisq 1 SPV resync. Confirm the receiving address or invoice in the trade chat; missing or inconsistent details need support before transfer. A completely settled trade with stale UI can be cleaned up only after confirming both deliveries and the appropriate action for that version.

## Payment details and evidence

A public nickname is not necessarily the legal account-holder name. If a bank cannot verify a name/IBAN, PIX recipient details conflict, or payment instructions change, pause and clarify the actual registered details privately in the trade chat. Do not bypass a warning because names look similar or pay an unrelated account. Escalate unresolved mismatches to mediation.

If payment is reversed or a fraud allegation arrives after BTC was sent, preserve payment records, trade chat and the BTC transaction ID. Verify the recipient of support evidence, agree an appropriate private channel and redact unrelated personal data. Never share wallet seeds or private keys. Mediation cannot guarantee a bank reversal, reimbursement or legal outcome.

ACH availability, limits and processing times depend on the bank. Do not confirm micro-deposit amounts for a peer or help them link your account; a small verification transfer is not trade payment. Resolve an unusable payment method before paying, and involve mediation if details or funds have already changed hands.

For cash by mail, agree recipient and delivery terms first, check the carrier's cash and insurance rules, use appropriate secure packaging and retain dispatch evidence. The general cash-by-mail guide has useful preparation advice, but its escrow and arbitration sections describe Bisq 1. Evidence can be difficult to establish; Easy mediation does not recreate that escrow protection.

## Amount limits

The official reputation documentation checked on 2026-09-18 describes an overall 600 USD-equivalent maximum, with seller reputation potentially limiting an offer below it. Verify the actual supported client and offer before quoting a numeric limit. The maximum is not a safety guarantee or a recommendation to trade that amount.

## Mediator mismatch at trade initiation

“Mediators do not match” means that the take-offer handler found a difference between the mediator in the taker’s contract and the mediator selected by the other peer. It does not call for manually selecting a named mediator. For a failed initial attempt before payment details or funds were exchanged, use the available failed-trade action and retry with a supported client. If details or money have already changed hands, preserve the trade and involve support/mediation rather than assuming cancellation returns funds.

## Evidence / Sources

- https://bisq.wiki/Bisq_Easy
- https://bisq.wiki/Dispute_Resolution_in_Bisq_2
- https://bisq.wiki/Reputation
- https://bisq.wiki/ACH
- https://bisq.wiki/Cash_by_Mail
- https://bisq.wiki/Dispute_resolution

- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/trade/src/main/java/bisq/trade/bisq_easy/protocol/messages/BisqEasyTakeOfferRequestHandler.java
- https://bisq.wiki/Bisq_Easy#Trade_rules

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 913, 922, 1095. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

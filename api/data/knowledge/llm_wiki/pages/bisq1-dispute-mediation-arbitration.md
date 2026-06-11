---
id: bisq1-dispute-mediation-arbitration
title: Bisq 1 mediation and arbitration flow
type: llm_wiki
page_type: support_playbook
status: proposed
protocol: multisig_v1
reviewed_by: null
reviewed_at: null
risk_level: high
source_refs:
  - wiki:Dispute Resolution in Bisq 1
  - wiki:Mediation
  - wiki:Arbitration
---
## Canonical Support Answer

Bisq 1 dispute resolution has stages: direct trader chat, mediation, and arbitration. Most problems should first be handled through trade chat and mediation. A mediator can assess the situation and propose a payout, but the mediator does not hold a multisig key and the proposal requires trader cooperation.

If the buyer paid fiat in Bisq 1 but BTC was not released, the user should open mediation and provide the requested proof of payment. If a bank transfer failed and both peers agree the trade should be cancelled or unwound, support should still route them through the mediator so the payout/cancellation proposal is documented and signed safely.

For "what happens if mediation is not accepted" or "how are disputed payouts and reimbursement handled", keep the answer focused: arbitration is the last-resort stage, the arbitrator investigates the evidence, makes the final payout decision, pays a trader if BTC is owed, and later requests reimbursement from the DAO.

For "when can arbitration be opened", include the timeout rule: the delayed payout transaction can be published only after the protocol timeout, typically 10 days after deposit confirmation for altcoin trades and 20 days after deposit confirmation for fiat trades. Support should tell users to cooperate with mediators/arbitrators, provide requested proof, and respond within the expected window. If a user cannot respond temporarily, they should tell the mediator/arbitrator in advance.

## Applies When

- The user asks what happens after mediation fails.
- The user asks when arbitration can be opened.
- The user asks who decides disputed payouts in Bisq 1.
- The user asks what proof to provide in mediation.
- The user paid fiat in Bisq 1 but BTC was not released.
- Both peers want to cancel a Bisq 1 trade after a failed bank transfer.

## Do Not Say

- Do not say the mediator can unilaterally move multisig funds.
- Do not recommend opening arbitration before the protocol makes it available.
- Do not promise a specific payout before mediator/arbitrator review.
- Do not describe Bisq 1 cancellation as a simple local reject button when funds or payment may be involved.
- Do not include delayed-payout timeout details when the user only asks how arbitration payout/reimbursement works.

## Evidence / Sources

- `wiki:Dispute Resolution in Bisq 1` describes trader chat, mediation, arbitration, response expectations, and payout suggestions.
- `wiki:Mediation` documents mediator duties and proof requests.
- `wiki:Arbitration` explains arbitration availability, delayed payout transaction mechanics, and DAO reimbursement.
- `wiki:Arbitration` documents the 10-day altcoin and 20-day fiat timeout before the delayed payout transaction can be published.

## Review Notes

- Current UI shortcuts/buttons for opening mediation/arbitration should be verified against the user's Bisq 1 version.

## Last Change Summary

Converted from generated support playbook into internal LLM Wiki page; ready for local support-admin review.

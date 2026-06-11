---
id: bisq2-easy-mediation-and-risk
title: Bisq Easy mediation and risk boundaries
type: llm_wiki
page_type: support_playbook
status: proposed
protocol: bisq_easy
reviewed_by: null
reviewed_at: null
risk_level: high
source_refs:
  - wiki:Bisq Easy
  - wiki:Dispute Resolution in Bisq 2
  - faq:20
  - faq:40
  - faq:47
  - faq:52
  - faq:88
  - faq:91
  - faq:92
  - faq:98
  - faq:873
  - faq:1069
  - faq:1070
  - faq:1068
---
## Canonical Support Answer

Bisq Easy is reputation-based and does not use the Bisq 1 multisig escrow/security-deposit model. If a trade has a problem, the first path is trade chat. Mediation can be requested from the trade screen, and a mediator can help traders complete or cancel the trade and can report serious rule violations.

Because there is no Bisq 1-style escrow in Bisq Easy, support should not promise reimbursement or DAO-backed recovery for every buyer loss. The safety model is to use small amounts, choose sellers with reputation, communicate clearly, and request mediation when payment was sent but BTC was not released.

After a buyer sends fiat, BTC release depends on the payment method and the seller confirming receipt. For ACH specifically, keep support guidance conservative: ACH can take 1-3 days, is not available for every bank account, and bank micro-deposit verification flows can be unsuitable for peer-to-peer payment. If the seller does not release BTC within the expected trade period for that payment method, the buyer should open mediation.

If the seller received fiat but a UI deadlock or mediation state blocks completion, support can ask the parties to coordinate in trade chat and, where appropriate, have the seller send BTC to the buyer's provided Bitcoin address.

## Applies When

- The user asks what happens if the seller does not release BTC.
- The user asks how long to wait after sending fiat in Bisq Easy.
- The user asks how ACH buying works in Bisq Easy.
- The user's bank requires ACH micro-deposit verification.
- The user asks whether Bisq Easy has escrow.
- The user asks when to request mediation.
- The user reports an unresponsive peer or stuck Bisq Easy trade.

## Do Not Say

- Do not describe Bisq Easy as having Bisq 1 multisig escrow.
- Do not promise reimbursement for Bisq Easy buyer losses.
- Do not state a fixed 24-hour BTC release deadline unless the specific payment method source supports it.
- Do not tell a seller to accept ACH micro-deposit verification as a normal peer-to-peer payment flow.
- Do not tell users to move the trade outside Bisq without preserving trade-chat coordination and support visibility.

## Evidence / Sources

- `wiki:Bisq Easy` documents reputation, no security deposit, and mediation support.
- `wiki:Dispute Resolution in Bisq 2` documents trade chat and Bisq Easy mediation.
- `faq:20`, `faq:88`, `faq:91`, and `faq:92` explain the non-escrow risk model.
- `faq:47`, `faq:52`, `faq:98`, and `faq:1068` cover unresponsive peers, stuck trades, mediation, and sent-fiat situations.
- `faq:1069` says ACH processing usually takes 1-3 days.
- `faq:873` warns that ACH micro-deposit verification is not intended for peer-to-peer payments and may require choosing another seller or payment method.

## Review Notes

- Confirm current UI labels for requesting mediation when giving step-by-step instructions.

## Last Change Summary

Converted from generated support playbook into internal LLM Wiki page; ready for local support-admin review.

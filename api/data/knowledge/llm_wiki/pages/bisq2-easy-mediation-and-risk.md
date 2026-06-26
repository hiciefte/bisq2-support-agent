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
  - wiki:Reputation
  - wiki:Reputation2
  - wiki:Trade Protocols
  - faq:19
  - faq:20
  - faq:27
  - faq:31
  - faq:40
  - faq:43
  - faq:46
  - faq:53
  - faq:85
  - faq:88
  - faq:873
  - faq:1068
  - faq:1069
  - faq:1070
---
## Canonical Support Answer

Bisq Easy is a Bisq 2 trade protocol for buying or selling BTC in small, reputation-based trades. It does not use the Bisq 1 multisig escrow/security-deposit model. The buyer normally sends fiat first, and the seller's reputation is the main trust signal. Because the security model is lighter than Bisq 1 multisig, support guidance should keep amounts small, encourage reputable sellers, and avoid implying DAO-backed reimbursement.

If no fiat has been sent and the peer is inactive, the user can usually reject/cancel the Bisq Easy trade and take another offer. If fiat has already been sent or the parties disagree about payment/BTC release, the user should not treat cancellation as resolution; they should use trade chat and request mediation or contact support from the trade context.

If a seller has received fiat but the UI state is stuck, support can help the parties complete safely in trade chat. For example, if the buyer's BTC address is missing from the structured trade state, the buyer may provide the BTC address in trade chat because the chat history is visible during mediation. The seller should send BTC only after they are satisfied payment was actually received and the address belongs to the buyer in that trade.

For ACH and similar payment methods, keep guidance conservative. ACH may take several days, is not available for every bank account, and bank micro-deposit verification must not be accepted as normal peer-to-peer payment. If the payment path cannot be completed safely, use another seller or payment method and involve mediation if funds were already sent.

Bisq Easy trade limits and seller eligibility depend on reputation and current client rules. Do not quote hard limits unless they are current for the user's version; when needed, explain that Bisq Easy is intended for relatively small BTC trades and that seller reputation controls buyer trust and available trade size.

Named traders, bots, and temporary incidents should not become reusable support policy. If the user names a specific seller/bot, keep the answer case-specific: ask them to use trade chat, wait for the payment method's normal processing time, and open mediation if BTC is not released or communication fails.

## Applies When

- The user asks what happens if the seller does not release BTC in Bisq Easy.
- The user asks how long to wait after sending fiat in Bisq Easy.
- The user's peer is inactive before fiat was sent.
- The user's peer is inactive after fiat was sent.
- The user asks whether Bisq Easy has escrow or security deposits.
- The user asks when to request mediation or reject/cancel a Bisq Easy trade.
- The user reports a missing BTC address, stuck state, or UI deadlock in a Bisq Easy trade.
- The user asks about ACH, micro-deposits, or payment-method timing in Bisq Easy.
- The user asks about Bisq Easy trade-size limits or reputation-related risk.

## Do Not Say

- Do not describe Bisq Easy as having Bisq 1 multisig escrow.
- Do not promise reimbursement for Bisq Easy buyer losses.
- Do not state a fixed BTC release deadline unless the specific payment method and source support it.
- Do not tell a seller to accept ACH micro-deposit verification as a normal peer-to-peer payment flow.
- Do not tell users to move negotiation outside Bisq when the built-in trade chat can preserve evidence.
- Do not encode named-bot or named-trader incidents as general policy.
- Do not say a trade can simply be rejected after fiat was sent without mediation/support review.

## Evidence / Sources

- `wiki:Bisq Easy` documents the reputation-based, no-security-deposit model and the seller-paid BTC transfer flow.
- `wiki:Dispute Resolution in Bisq 2` documents trade chat and Bisq Easy mediation.
- `wiki:Reputation` and `wiki:Reputation2` document reputation as the Bisq Easy security mechanism and its relationship to trade limits.
- `wiki:Trade Protocols` says Bisq Easy is the currently implemented Bisq 2 protocol and future protocols are separate.
- `faq:19`, `faq:20`, `faq:27`, `faq:31`, `faq:40`, `faq:43`, `faq:46`, `faq:53`, `faq:85`, and `faq:88` cover stuck trades, non-escrow risk, address sharing, mediation, and Bisq 1/Bisq Easy distinction.
- `faq:873`, `faq:1068`, `faq:1069`, and `faq:1070` cover ACH timing and micro-deposit boundaries.

## Review Notes

- Confirm current UI labels for requesting mediation or rejecting a trade before giving step-by-step instructions.
- Check current release notes before quoting exact trade-limit numbers.
- Several production candidates about specific sellers/bots, temporary offer expiry, or protobuf/network repair were intentionally not promoted into this durable risk page.

## Last Change Summary

Cleaned the reviewed production page and merged recurring Bisq Easy risk, cancellation, stuck-trade, address-sharing, ACH, and mediation candidates into one conservative support playbook.

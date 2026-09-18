---
id: bisq1-payment-method-checks
title: Bisq 1 ACH, Revolut, Wise and initial funding checks
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: medium
source_refs:
- wiki:ACH Transfer
- wiki:Revolut
- wiki:Wise
- wiki:Payment methods
- wiki:Funding your wallet
- wiki:Trading rules
- wiki:Bisq Easy
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/core/src/main/java/bisq/core/payment/payload/RevolutAccountPayload.java#L147
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/desktop/src/main/java/bisq/desktop/main/overlays/windows/UpdateRevolutAccountWindow.java
- https://bisq.wiki/Trading_rules#Do_not_change_payment_details_once_trade_is_in_progress
- https://bisq.wiki/Dispute_Resolution_in_Bisq_1
---
## Scope and initial funds

These method-specific rules concern conventional Bisq 1 trades. Its wallet receives BTC, not fiat bank deposits: `Funds > Receive Funds` supplies a Bitcoin address. Send BTC there from a Bitcoin wallet. The fiat leg goes directly between buyer and seller through the agreed payment method. Starting a Bisq 1 trade requires the displayed BTC deposit and fees, not a guaranteed fixed fiat-equivalent amount. Bisq Easy is a separate deposit-free option for obtaining initial BTC; do not apply the Bisq 1 wallet setup to it.

Bisq 1 restricts methods with easy chargebacks, such as PayPal. Check its supported methods and actual offer terms before trading. A provider's ability to send some kind of transfer does not authorize substituting it for the method/account agreed in an active trade.

## ACH capability and microdeposits

Confirm with the bank that it supports payments to third parties. Ability to receive ACH, or to link another account you own, does not establish that capability. Do not misrepresent the seller's account as your own. Never ask a peer to confirm microdeposit amounts or confirm them for a buyer: this can link the accounts and enable debits. Use an actual third-party transfer service supported by the bank, not account-linking verification.

If the bank cannot make the agreed payment, inform the peer and open Bisq 1 mediation before trying another method/account. A recipient postal address and a bank routing number are different fields; clarify the actual problem. Check transfer capability and limits before future trades.

## Revolut details and warnings

The Bisq 1 Revolut method uses Revolut-to-Revolut payments with the recorded Revtag. Its official guide excludes using a Revolut IBAN for Bisq 1 SEPA; this restriction does not mean Revolut lacks IBANs. Verify Bisq 2 rules separately.

Payment-account details cannot simply be edited after creation. The legacy missing-username migration described below is a specific exception; changing an already-set Revtag is different. Create a correctly specified account for future offers when the Revtag changes, preserving the existing trade evidence. Doing so does not change an active contract. If the recorded Revtag cannot be found, ask the peer to clarify and use official Revolut troubleshooting; do not pay an informally substituted destination. Involve mediation if unresolved.

A matching Revtag does not prove a scam warning is harmless. Investigate in Revolut's official app/support, keep the warning and payment evidence and tell the peer. Use mediation if safe payment cannot proceed. Do not bypass a warning under pressure or guarantee a dispute outcome.

## Wise is a payment-method distinction

Wise-to-Wise uses the registered account email and is distinct from bank-transfer details supplied by Wise for another supported method. The current Bisq method list marks Wise/Wise-USD as not requiring signing; that does not exempt a separate SEPA account merely because Wise supplies it. Use the actual method-specific rules and recorded destination. If a seller supplies a replacement link or says their account is frozen after payment, do not send again: preserve evidence and resolve it through the trade's mediation.

## Legacy Revolut account missing a username

Back up the complete Bisq data first. Bisq has a specific migration prompt for old Revolut accounts whose username was never set: it adds the username to the existing account and preserves the old accountId used by its age witness. Use that supported migration if offered; do not recreate the account or replace signing-key files to imitate it. This does not authorize changing an already-set Revtag or rewrite an active trade contract. For an active refusal to pay, select the trade and request mediation; the trade period need not expire before requesting help.

## Evidence / Sources

- [ACH Transfer](https://bisq.wiki/ACH_Transfer): third-party transfer capability, microdeposit account-linking risk and bank limits.
- [Revolut](https://bisq.wiki/Revolut): Bisq 1 scope, Revtag, immutable details and SEPA restriction.
- [Revolut fraud guidance](https://www.revolut.com/en-US/about-fraud-and-scam/): investigate warnings through official channels.
- [Wise](https://bisq.wiki/Wise) and [Payment methods](https://bisq.wiki/Payment_methods): Wise method versus bank details and signing scope.
- [Funding your wallet](https://bisq.wiki/Funding_your_wallet), [Trading rules](https://bisq.wiki/Trading_rules), [Bisq Easy](https://bisq.wiki/Bisq_Easy): separate BTC funding, peer fiat payment and protocol requirements.

- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/core/src/main/java/bisq/core/payment/payload/RevolutAccountPayload.java#L147
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/desktop/src/main/java/bisq/desktop/main/overlays/windows/UpdateRevolutAccountWindow.java
- https://bisq.wiki/Trading_rules#Do_not_change_payment_details_once_trade_is_in_progress
- https://bisq.wiki/Dispute_Resolution_in_Bisq_1

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 1078. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

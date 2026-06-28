---
id: bisq1-sepa-payment-name-proof
title: Bisq 1 SEPA payment details, sender name, and proof
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: suddenwhipvapor
reviewed_at: '2026-06-27'
risk_level: high
source_refs:
- wiki:SEPA
- wiki:SEPA Instant
- wiki:Payment methods
- wiki:Trading rules
- wiki:Dispute Resolution in Bisq 1
- wiki:Mediation
- faq:1155
- faq:1183
---
## Canonical Support Answer

For SEPA and SEPA Instant trades, account details, sender identity, payment reference, timing, and proof matter because mediators may need to verify whether payment was sent correctly and on time. When adding a SEPA account, the user must enter their name as shown by the bank, along with correct IBAN/BIC details.

If an incoming payment name, IBAN, or bank account does not match the Bisq trade details, the seller should not release the BTC, but rather open mediation, especially when confirming the trade would sign the buyer's account. The mediator will request an explanation from the buyer, and evaluate the best course of action together with the traders.

When the originating payment details match, and name mismatch is marginal, like "Name A. Surname" instead of "Name Surname" (or vice versa), or "N. Surname" instead of "Name Surname", and in similar situations where it is evident that the mismatch still refers to the same person, it is allowed to complete the trade normally.

If SEPA Instant fails but the same account details can receive a normal SEPA transfer, the peers may continue if both agree and the payment still goes to the same name/account shown in the trade details. If the recipient account, account holder, or payment method materially changes, involve mediation instead of improvising a new off-contract payment path.

Never use a payment reference for the fiat transfer. Reference field should be left blank, or, when this is not possible, be filled with the buyer's Name Surname.

If a payment reference is used that the peers did not agree on ahead of time, the seller should not release the BTC, but open mediation.

If the buyer sends payment late, with wrong details, or from an unexpected name/account, the case belongs in the Bisq 1 dispute-resolution flow rather than informal support instructions.

## Applies When

- The seller sees a SEPA incoming name mismatch.
- The buyer used a payment reference instead of leaving it blank.
- The buyer asks what reference/name to use for SEPA.
- A SEPA Instant payment fails and the peer proposes normal SEPA instead.
- A fiat payment was sent but the BTC seller is unsure whether to release.
- The bank rejects or blocks a payment because the recipient name/account cannot be verified.
- A mediator asks for payment proof.

## Do Not Say

- Do not tell sellers to release BTC when payment identity is uncertain.
- Do not ask users to post sensitive bank documents publicly.
- Do not treat all name mismatches as automatically fraudulent or automatically safe.
- Do not approve sending funds to a different account or name than the trade details without mediation.
- Do not allow the use of custom payment references.

## Evidence / Sources

- `wiki:SEPA` and `wiki:SEPA Instant` describe correct SEPA account details and payment-method constraints.
- `wiki:Payment methods` documents payment-method risk and account detail boundaries.
- `wiki:Trading rules` documents that payment-rule violations can affect dispute outcomes.
- `wiki:Dispute Resolution in Bisq 1` explains trader chat and mediation.
- `wiki:Mediation` documents proof-of-payment and banking-issue evidence requests.
- `faq:1155` and `faq:1183` cover invalid bank details and fallback from SEPA Instant to normal SEPA when both peers agree and details remain consistent.

## Review Notes

- Specific penalty outcomes should be left to mediator/arbitrator review.

## Last Change Summary

Expanded SEPA guidance to include normal-SEPA fallback, bank verification/name mismatch, payment-reference caution, and mediation boundaries.

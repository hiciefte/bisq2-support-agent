---
id: bisq1-sepa-payment-name-proof
title: Bisq 1 SEPA payment details, sender name, and proof
type: llm_wiki
page_type: support_playbook
status: proposed
protocol: multisig_v1
reviewed_by: null
reviewed_at: null
risk_level: high
source_refs:
  - wiki:SEPA
  - wiki:Dispute Resolution in Bisq 1
  - wiki:Mediation
---
## Canonical Support Answer

For SEPA trades, account details and sender identity matter because mediators may need to verify whether payment was sent correctly and on time. When adding a SEPA account, the user should enter their name as shown by the bank, along with correct IBAN/BIC details.

If an incoming payment name does not match expected details, the seller should not guess or release BTC blindly. The correct path is to communicate in trader chat and, if unresolved, involve mediation. The mediator may request proof from the buyer and may ask the seller to verify their account details.

If the buyer sends payment late, with wrong details, or from an unexpected name/account, the case belongs in the Bisq 1 dispute-resolution flow rather than informal support instructions.

## Applies When

- The seller sees a SEPA incoming name mismatch.
- The buyer asks what reference/name to use for SEPA.
- A fiat payment was sent but the BTC seller is unsure whether to release.
- A mediator asks for payment proof.

## Do Not Say

- Do not tell sellers to release BTC when payment identity is uncertain.
- Do not ask users to post sensitive bank documents publicly.
- Do not treat all name mismatches as automatically fraudulent or automatically safe.

## Evidence / Sources

- `wiki:SEPA` describes correct SEPA account details, payment reference guidance, and mediator proof expectations.
- `wiki:Dispute Resolution in Bisq 1` explains trader chat and mediation.
- `wiki:Mediation` documents proof-of-payment and banking-issue evidence requests.

## Review Notes

- Specific penalty outcomes should be left to mediator/arbitrator review.

## Last Change Summary

Converted from generated support playbook into internal LLM Wiki page; ready for local support-admin review.

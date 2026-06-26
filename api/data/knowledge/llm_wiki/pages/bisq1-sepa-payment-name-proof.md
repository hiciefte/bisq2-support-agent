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
  - wiki:SEPA Instant
  - wiki:Payment methods
  - wiki:Trading rules
  - wiki:Dispute Resolution in Bisq 1
  - wiki:Mediation
  - faq:1155
  - faq:1183
---
## Canonical Support Answer

For SEPA and SEPA Instant trades, account details, sender identity, payment reference, timing, and proof matter because mediators may need to verify whether payment was sent correctly and on time. When adding a SEPA account, the user should enter their name as shown by the bank, along with correct IBAN/BIC details.

If an incoming payment name, IBAN, or bank account does not match the Bisq trade details, the seller should not guess or release BTC blindly. The correct path is to communicate in trader chat and, if unresolved, involve mediation. The mediator may request proof from the buyer and may ask the seller to verify their account details.

If SEPA Instant fails but the same account details can receive a normal SEPA transfer, the peers may continue only if both agree and the payment still goes to the same name/account shown in the trade details. If the recipient account, account holder, or payment method materially changes, involve mediation instead of improvising a new off-contract payment path.

Payment references can vary by version/payment method. Follow the trade contract and current UI instructions. If there is no explicit trade-ID reference requirement in the current Bisq 1 flow, do not invent one; however, users should still avoid payment references that disclose sensitive or suspicious wording beyond what the trade requires.

If the buyer sends payment late, with wrong details, or from an unexpected name/account, the case belongs in the Bisq 1 dispute-resolution flow rather than informal support instructions.

## Applies When

- The seller sees a SEPA incoming name mismatch.
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
- Do not invent a payment-reference requirement that the current trade UI does not require.

## Evidence / Sources

- `wiki:SEPA` and `wiki:SEPA Instant` describe correct SEPA account details and payment-method constraints.
- `wiki:Payment methods` documents payment-method risk and account detail boundaries.
- `wiki:Trading rules` documents that payment-rule violations can affect dispute outcomes.
- `wiki:Dispute Resolution in Bisq 1` explains trader chat and mediation.
- `wiki:Mediation` documents proof-of-payment and banking-issue evidence requests.
- `faq:1155` and `faq:1183` cover invalid bank details and fallback from SEPA Instant to normal SEPA when both peers agree and details remain consistent.

## Review Notes

- Specific penalty outcomes should be left to mediator/arbitrator review.
- Verify current Bisq 1 UI wording for payment references before giving exact instructions.

## Last Change Summary

Expanded SEPA guidance to include normal-SEPA fallback, bank verification/name mismatch, payment-reference caution, and mediation boundaries.

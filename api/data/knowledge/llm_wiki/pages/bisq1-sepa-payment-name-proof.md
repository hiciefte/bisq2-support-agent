---
id: bisq1-sepa-payment-name-proof
title: Bisq 1 SEPA and fiat payment identity, references and proof
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: high
source_refs:
- wiki:SEPA
- wiki:SEPA Instant
- wiki:Trading rules
- wiki:Creating a payment account
- wiki:Payment methods
- wiki:Mediation
- wiki:Table of penalties
- wiki:Dispute Resolution in Bisq 1
- wiki:Revolut
- https://bisq.wiki/Trading_rules#Click_Confirm_payment_after_receiving_payment
- https://bisq.wiki/Account_limits
- https://bisq.wiki/Security_deposit
---
## Account details and privacy

For Bisq 1 SEPA, enter the account-holder name as displayed by the bank and accurate IBAN/BIC details. The local nickname used to label a payment account is different from its holder's name. Check the offer's accepted bank countries, including Gibraltar where relevant, as well as applicable amount limits. Signing does not override country compatibility.

Payment details are stored in local application data and shared with the trading peer for settlement, not placed in a centralized public customer database. Necessary evidence may also be shared with a mediator/arbitrator in a dispute. This does not make the details anonymous to the bank or counterparty. Do not invent details or omit a required holder name. If a bank requires a recipient postal address, clarify the requirement and obtain accurate details privately from the peer; if unavailable or inconsistent, seek mediation rather than fabricating an address.

## Verify receipt and identity before releasing BTC

Check actual receipt in the bank/payment account, amount and available sender details against the trade contract. Payment Started, a screenshot or a peer's assurance is not proof of bank receipt. Missing sender information is not proof of a match. Materially different names, accounts or institutions require immediate mediation before confirming; in Bisq 1 select the trade and use `Ctrl+O` (`Cmd+O` on macOS), then explain the issue in Support. Do not wait for the payment period to expire when a known mismatch already exists.

A clearly recognizable minor bank-name formatting variation can refer to the same person, but initials alone, a different legal/business identity or unexplained third-party payment must not be automatically accepted. Account signing or age does not resolve an identity mismatch or guarantee honesty. Let the mediator evaluate uncertain evidence; do not promise a fixed penalty or assume every difference is fraud.

## Changed, rejected or reversed payments

Use the account and method agreed for the trade. For an unusable bank account, invalid recipient, incorrect Revtag, replacement Wise link or a request to pay another account, pause and involve mediation before using substitute details. Editing a local payment account does not rewrite an active trade contract. Discuss problems in trade chat and retain its record; do not move the negotiation to unsolicited off-platform contacts.

A SEPA Instant transfer may fall back to normal SEPA when both peers agree to the longer timing and the same account-holder/account details remain in use. This narrow exception is not general permission to substitute payment methods or destinations. For material changes, uncertainty or a silent peer, use mediation.

If payment was already sent to a closed or frozen account, reversed, recalled or disputed, verify its actual status with the bank and preserve the evidence. Do not assume it returned, send a duplicate payment, or release BTC merely because payment was marked started. Inform the peer and mediator. Pending trades with the same peer do not authorize taking their funds as compensation for an earlier recall. Avoid uncoordinated refunds, test payments or alternative destinations; case evidence determines the resolution.

A bank fraud warning is neither conclusive proof of fraud nor something to dismiss because details match. Pause, investigate through the provider's official channel and involve the mediator if safe payment cannot proceed. There is no guarantee of reimbursement.

## References and private evidence

For SEPA, leave the payment reference blank; if the bank requires one, use your bank account name as the SEPA guide specifies. Do not put the trade ID or cryptocurrency-related wording in the reference. For other fiat methods, follow the current method-specific guide and Trading rules rather than assuming an identical fallback. A problematic reference should be discussed with the mediator, not silently converted into a guaranteed penalty.

Provide necessary payment proof privately through verified dispute channels, redacting unrelated information. Do not publish bank statements or card details. If the peer demands excessive personal evidence beyond the method's needs, pause and ask the mediator what is required; legitimate dispute evidence is different from an unlimited disclosure demand.

## Timing when signing a buyer account

For a trade in which a signed seller signs the buyer’s account, the official rules recommend waiting until near the end of the permitted trade period before confirming receipt to reduce chargeback risk. This is not permission to miss the deadline, ignore mismatched payer details, or treat signing/deposits as a guarantee. Verify actual payment and involve mediation promptly when details differ.

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 444. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Evidence / Sources

- [SEPA](https://bisq.wiki/SEPA): official procedure or scope referenced above.
- [SEPA Instant](https://bisq.wiki/SEPA_Instant): official procedure or scope referenced above.
- [Trading rules](https://bisq.wiki/Trading_rules): official procedure or scope referenced above.
- [Creating a payment account](https://bisq.wiki/Creating_a_payment_account): official procedure or scope referenced above.
- [Payment methods](https://bisq.wiki/Payment_methods): official procedure or scope referenced above.
- [Mediation](https://bisq.wiki/Mediation): official procedure or scope referenced above.
- [Table of penalties](https://bisq.wiki/Table_of_penalties): official procedure or scope referenced above.
- [Dispute Resolution in Bisq 1](https://bisq.wiki/Dispute_Resolution_in_Bisq_1): official procedure or scope referenced above.
- [Revolut](https://bisq.wiki/Revolut): official procedure or scope referenced above.

- https://bisq.wiki/Trading_rules#Click_Confirm_payment_after_receiving_payment
- https://bisq.wiki/Account_limits
- https://bisq.wiki/Security_deposit

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

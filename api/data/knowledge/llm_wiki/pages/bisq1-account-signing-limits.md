---
id: bisq1-account-signing-limits
title: Bisq 1 payment-account signing and buying limits
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-batch-20260918
reviewed_at: '2026-09-18T08:30:52.377693+00:00'
risk_level: medium
source_refs:
- wiki:Account limits
- wiki:Payment methods
- wiki:Creating a payment account
- wiki:Reputation
- wiki:Restoring application data
---
## Getting signed and higher limits

Signing applies to specified Bisq 1 payment methods and markets. A qualifying completed BTC purchase signs the buyer automatically when the seller is eligible; no separate manual favor is needed. Selling BTC to a signed buyer does not sign the seller. Check the offer badge and current Account limits guide for the eligible amount and method. The signing seller must have been signed for over 30 days; ordinary account age is not equivalent.

Check status and limits in `Account > National Currency Accounts`. Increased buying limits wait from signing, not account creation or an arbitrary past trade. The maximum depends on the method; selling limits are not phased in by signing. Missing signing calls for checking trade direction, eligibility and successful completion before diagnosing a bug.

Self-signing is different: it requires an eligible fully matured signed account and an eligible new account with the exact same holder name. A local nickname is irrelevant. Methods without the required full-name field cannot use this route. Self-signing does not immediately lift buying limits.

## Interpret identity and protocol correctly

One Bisq identity can use different payment accounts. A previously seen peer now offering an unsigned account may be using another account; compare the actual account/method rather than treating prior contact as proof of its status. Unexpected changes to the same account need investigation.

Wise-to-Wise is a distinct method listed without signing; Wise bank details used for another method do not inherit that exemption. See the payment-method page. Signing and age mitigate particular risks; neither is identity verification or a guarantee of honesty. An unsigned seller is not automatically barred from selling BTC. Follow the Bisq 1 deposit and dispute workflow without promising compensation.

Bisq 1 has local records of trades with peers, not a centralized public completed-trade score. Do not confuse those records or signing with Bisq Easy seller reputation: Easy reputation sources are not a completed-trade counter. Its protocol has different safeguards.

## Evidence / Sources

- [Account limits](https://bisq.wiki/Account_limits): trade-based signing, self-signing and limit maturity; check current amounts rather than historical thresholds.
- [Payment methods](https://bisq.wiki/Payment_methods): method-specific signing scope, including Wise.
- [Creating a payment account](https://bisq.wiki/Creating_a_payment_account): account-holder data versus private local label.
- [Restoring application data](https://bisq.wiki/Restoring_application_data): local peer history and preservation of signing state.
- [Reputation](https://bisq.wiki/Reputation): Bisq Easy reputation is separate from Bisq 1 account signing.

## Review Notes

New page consolidates automatic signing, correct trade direction, signer eligibility, self-signing and post-signing limits. Avoids stale numerical trade thresholds and using ordinary account age as proof of trust. No claim that all methods need signing.

## Last Change Summary

Independently reviewed consolidated guidance. Reviewer: `ai-review:codex:knowledge-batch-20260918`.

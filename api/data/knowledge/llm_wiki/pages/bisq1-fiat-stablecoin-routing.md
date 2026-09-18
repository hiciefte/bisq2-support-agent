---
id: bisq1-fiat-stablecoin-routing
title: Bisq 1 BTC, fiat and altcoin trade routes
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-batch-20260918
reviewed_at: '2026-09-18T08:30:52.377693+00:00'
risk_level: high
source_refs:
- https://bisq.wiki/Payment_methods
- https://bisq.wiki/Trading_Monero
- https://bisq.wiki/Security_deposit
- https://bisq.wiki/Frequently_asked_questions
---
## Canonical Support Answer

Bisq 1 coordinates peer-to-peer markets against BTC; users do not deposit fiat with Bisq as a broker. For fiat-to-altcoin or fiat-to-stablecoin exchange, the route is fiat to BTC with a peer, then BTC to the supported altcoin with another peer, or the reverse. Check current markets, supported payment methods and actual available offers rather than promising liquidity.

BTC/XMR trading uses Bisq 1's multisig protocol and its funding, security-deposit and fee requirements. It does not require acquiring Bisq Easy seller reputation. The person selling BTC receives XMR; the person buying BTC sends XMR. Verify actual payment in the relevant wallet before confirming receipt, and use the trade's mediation process for problems. Bisq Easy's reputation-based workflow and Bisq 1's security-deposit workflow must not be mixed.

Direct credit-card payment is not a supported Bisq 1 peer payment method. Check the current supported-method list; buying an eligible gift card elsewhere is a different payment path, not direct card processing by Bisq. Do not instruct users to send fiat to Bisq or guarantee risk-free trading.

## Applies When

Fiat-to-altcoin/stablecoin routing, BTC/XMR trade prerequisites, or confusion between Bisq Easy reputation and Bisq 1 multisig deposits.


## Evidence / Sources

- [Payment methods](https://bisq.wiki/Payment_methods)
- [Trading Monero](https://bisq.wiki/Trading_Monero)
- [Security deposit](https://bisq.wiki/Security_deposit)
- [Frequently asked questions](https://bisq.wiki/Frequently_asked_questions)

## Review Notes

Independently reviewed by the parent AI reviewer. Preserve private case evidence outside this reusable page.

## Last Change Summary

Preserved noncustodial BTC routing and clarified Bisq 1 BTC/XMR prerequisites without Easy reputation.

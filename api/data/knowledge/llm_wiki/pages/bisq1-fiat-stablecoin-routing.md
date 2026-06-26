---
id: bisq1-fiat-stablecoin-routing
title: Bisq 1 fiat, BTC, and stablecoin routing
type: llm_wiki
page_type: support_playbook
status: proposed
protocol: multisig_v1
reviewed_by: null
reviewed_at: null
risk_level: low
source_refs:
  - wiki:Payment methods
  - wiki:Trading Monero
  - wiki:Trade Protocols
  - faq:1041
---
## Canonical Support Answer

Users do not send fiat currency to Bisq itself. Bisq coordinates peer-to-peer trades between users. For fiat-to-altcoin paths in Bisq 1, the normal support guidance is that the user buys BTC with fiat from a peer and then uses BTC markets for supported altcoin trades where available.

If the user asks about buying stablecoins directly with fiat through Bisq, answer that Bisq does not receive fiat and does not act as a stablecoin broker. If a supported market exists, it is still a peer-to-peer trade with the available protocol, market, liquidity, and payment-method constraints.

Users can check the relevant Bisq market tabs for current offers and completed trade activity. Do not promise stablecoin liquidity or imply that a specific non-BTC market is currently active without checking the current offerbook/market data.

## Applies When

- The user asks whether to send fiat to Bisq.
- The user asks how to buy stablecoins with fiat through Bisq.
- The user asks how to move from fiat to altcoins using Bisq 1.
- The user confuses Bisq with a custodial exchange or broker.

## Do Not Say

- Do not provide deposit instructions to send fiat to Bisq.
- Do not imply Bisq custody or converts fiat on behalf of users.
- Do not promise stablecoin or altcoin market liquidity.
- Do not describe future Bisq 2 protocols as currently available production routes.

## Evidence / Sources

- `faq:1041` says users cannot send fiat to Bisq to buy stablecoins; they can buy BTC with fiat and then trade BTC for altcoins on Bisq 1.
- `wiki:Payment methods` documents peer-to-peer payment methods.
- `wiki:Trading Monero` establishes BTC-based altcoin trading patterns in Bisq 1.
- `wiki:Trade Protocols` distinguishes future protocol ideas from current production behavior.

## Review Notes

- Verify whether a specific altcoin/stablecoin market is currently available before giving market-specific guidance.

## Last Change Summary

Cleaned the production-approved page and returned it to proposed status for bootstrap review.

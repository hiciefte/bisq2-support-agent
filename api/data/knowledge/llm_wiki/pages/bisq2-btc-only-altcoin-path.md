---
id: bisq2-btc-only-altcoin-path
title: Bisq Easy scope, offers and choosing a trading protocol
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: bisq_easy
reviewed_by: ai-review:codex:knowledge-batch-20260918
reviewed_at: '2026-09-18T08:30:52.377693+00:00'
risk_level: medium
source_refs:
- https://bisq.wiki/Bisq_Easy
- https://bisq.network/blog/bisq-2-now-in-beta/
- https://bisq.wiki/Trade_Protocols
- https://github.com/bisq-network/bisq2/issues
- https://bisq.wiki/Trading_Monero
---
## Canonical Support Answer

Bisq Easy is available in Bisq 2. Its first public beta was announced on 16 March 2024; that date is a release milestone, not the start of development. Bisq 2 is a separate application, not an in-place upgrade or import target for a Bisq 1 wallet and active trades.

Bisq Easy is designed for smaller Bitcoin purchases, including obtaining a first on-chain UTXO without a BTC security deposit. It supports buying and selling BTC. The official guide also allows agreed fiat or altcoin payment arrangements: do not turn BTC-focused into a categorical ban on all altcoin payment. This does not establish arbitrary fiat-to-stablecoin or altcoin-to-altcoin markets, custody, or liquidity.

For a user specifically seeking an established BTC/XMR market, explain the Bisq 1 route and the need for an external XMR wallet, BTC fees and a security deposit. A fiat-to-XMR route may involve acquiring BTC first and then trading BTC for XMR. Do not invent an internal XMR wallet in Bisq Easy. Bisq Easy seller reputation is not a prerequisite for a Bisq 1 multisig trade.

Choose based on the supported market, payment method, trade amount and security model. Compare actual current offers and fees. Do not promise that one product always has better prices, smaller spreads or greater liquidity. Onboarding is an intended use case, not a prohibition on experienced users. Do not describe future protocols as already available merely because they appear in a roadmap.

## Finding and managing offers

Open the Bisq Easy offer book and select the relevant currency market to browse offers. Review actual amounts, price and payment methods before accepting. For an offer you created, use its own management menu to remove or modify it; some desktop versions show a three-dot menu. Exact position varies by version. Removing an offer prevents further acceptance but does not cancel trades already created from it.

Payment goes directly between the traders using their agreed method; Bisq does not receive a bank deposit on their behalf. To request a new currency, check existing Bisq 2 issues and submit the intended use plus reliable market-data sources if available. Maintainers decide feasibility; there is no guaranteed addition or mandatory DAO approval inferred from a support message.

## Evidence / Sources

- https://bisq.wiki/Bisq_Easy
- https://bisq.network/blog/bisq-2-now-in-beta/
- https://bisq.wiki/Trade_Protocols
- https://github.com/bisq-network/bisq2/issues
- https://bisq.wiki/Trading_Monero

## Review Notes

Independently reviewed by the parent AI reviewer after individual candidate review. Reviewer: `ai-review:codex:knowledge-batch-20260918`. Sources checked on 2026-09-18; verify release-sensitive behavior against the user's installed version.

## Last Change Summary

Removed permanent liquidity and absolute altcoin-payment claims. Added dated launch, separate-app boundary, offer management and currency-request guidance without historical version guesses.

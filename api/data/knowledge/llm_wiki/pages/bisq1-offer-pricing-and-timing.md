---
id: bisq1-offer-pricing-and-timing
title: Bisq 1 offer pricing and completion timing
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: high
source_refs:
- https://github.com/bisq-network/bisq/blob/master/apitest/docs/api-beta-test-guide.md
- https://bisq.wiki/SEPA
- https://bisq.wiki/Trading_rules
- https://bisq.wiki/Taking_an_offer
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/offer/Offer.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/desktop/src/main/java/bisq/desktop/main/offer/offerbook/OfferBookViewModel.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/util/PriceUtil.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/desktop/src/main/java/bisq/desktop/main/offer/bisq_v1/MutableOfferDataModel.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/resources/i18n/displayStrings.properties
- https://bisq.wiki/Wallet
- https://github.com/bisq-network/bisq/blob/8b381bfb45edd3912f2082d5af0db1dac9ceed43/desktop/src/main/java/bisq/desktop/main/portfolio/closedtrades/ClosedTradesView.java#L298-L332
- https://github.com/bisq-network/bisq/blob/8b381bfb45edd3912f2082d5af0db1dac9ceed43/desktop/src/main/java/bisq/desktop/main/funds/transactions/TransactionsView.java#L251-L274
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/util/AveragePriceUtil.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/desktop/src/main/java/bisq/desktop/main/dao/economy/dashboard/BsqDashboardView.java
---
## Canonical Support Answer

A market-relative offer uses a percentage margin from its reference market price while available. A fixed-price offer uses the chosen price and can move above or below the market. Review the actual BTC amount, fiat total and price before taking an offer. Historical example prices and trade sizes are not current limits. The separate BSQ section below describes its version-scoped reference calculation.

Finding an offer or a taker depends on market activity, payment method, amount and price; there is no guaranteed matching time. After acceptance, Bitcoin deposit confirmation and the chosen payment method add separate delays. Standard SEPA can take working days, while other methods differ; use the actual trade period and method documentation. Disputes or technical issues can extend completion. Buying BTC settles into the Bisq wallet through the trade payout with the buyer's returned deposit; it is not an instant custodial fiat deposit.

## Applies When

Fixed versus relative pricing, expected time to find a trade, or confusion between fiat-payment timing and Bitcoin confirmation.

## Trade direction, quantity and market margin

Interpret the displayed margin with the trade direction. In the reviewed Bisq 1 fiat pricing code, a maker BUY offer uses one minus its margin. Thus a taker selling BTC into a maker BUY offer with a -6% margin receives about 106% of the reference fiat price, before fees and rounding. Maker SELL pricing uses the opposite sign. Verify the actual fiat total divided by BTC before accepting.

A percentage margin sets the unit price, not the trade quantity. Bisq 1 calculates fiat volume from a valid BTC amount and price, or derives BTC from the entered fiat volume with rounding and limits. A market-relative quote can change while open; choosing a fixed unit price is not alone a universal budget cap. Bisq 1 settles purchased BTC into its internal wallet, unlike Easy’s external receiving-address flow.

## Historical CSV exports and the BSQ reference price

Official Bisq 1.9.15 closed-trade history exports tradeHistory.csv with price and deviation columns. That export is unchanged from 1.9.14. Funds transaction history instead exports transactions.csv with wallet-transaction fields, not trade execution prices. Check the selected screen and report before assuming a price column was removed or downgrading.

The latest individual BSQ/BTC trade price is distinct from its average reference. In the reviewed Bisq 1.10.8 code, a fixed-price BSQ offer without a recent external quote uses the 30-day BSQ/BTC average. It divides total BTC by total BSQ traded over the selected statistics, with configured outlier trimming. The DAO economy dashboard exposes the 30-day average. Percentage signs remain direction-sensitive, and this BSQ-specific fallback is not the reference for every market.

## Evidence / Sources

- [api-beta-test-guide.md](https://github.com/bisq-network/bisq/blob/master/apitest/docs/api-beta-test-guide.md)
- [SEPA](https://bisq.wiki/SEPA)
- [Trading rules](https://bisq.wiki/Trading_rules)
- [Taking an offer](https://bisq.wiki/Taking_an_offer)

- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/offer/Offer.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/desktop/src/main/java/bisq/desktop/main/offer/offerbook/OfferBookViewModel.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/util/PriceUtil.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/desktop/src/main/java/bisq/desktop/main/offer/bisq_v1/MutableOfferDataModel.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/resources/i18n/displayStrings.properties
- https://bisq.wiki/Wallet
- https://github.com/bisq-network/bisq/blob/8b381bfb45edd3912f2082d5af0db1dac9ceed43/desktop/src/main/java/bisq/desktop/main/portfolio/closedtrades/ClosedTradesView.java#L298-L332
- https://github.com/bisq-network/bisq/blob/8b381bfb45edd3912f2082d5af0db1dac9ceed43/desktop/src/main/java/bisq/desktop/main/funds/transactions/TransactionsView.java#L251-L274
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/util/AveragePriceUtil.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/desktop/src/main/java/bisq/desktop/main/dao/economy/dashboard/BsqDashboardView.java

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 549, 1375, 1405, 1753. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

---
id: payment-method-and-price-checks
title: Payment-method capability, trade amounts and price-reference checks
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: all
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: medium
source_refs:
- wiki:Trading rules
- wiki:Bisq Easy
- wiki:Payment methods
- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/apps/desktop/desktop/src/main/java/bisq/desktop/main/content/bisq_easy/history/BisqEasyTradeHistoryListItem.java
- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/apps/desktop/desktop/src/main/java/bisq/desktop/main/content/bisq_easy/history/BisqEasyHistoryView.java
- https://github.com/bisq-network/bisq/blob/8b381bfb45edd3912f2082d5af0db1dac9ceed43/desktop/src/main/java/bisq/desktop/main/portfolio/closedtrades/ClosedTradesView.java
- https://bisq.wiki/Bisq_Price_Indices
- https://bisq.wiki/Bisq_Easy
- https://bisq.wiki/Amazon_eGift_card
- https://digprjsurvey.amazon.co.uk/csad/help/node/GNG9PXYZUMQT72QK
---
## Scope

These checks apply before or during a Bisq trade, but specific deposits, account signing, keyboard shortcuts and dispute payouts depend on the selected protocol. Establish whether the user is in Bisq 1 or Bisq Easy before giving those instructions.

## Agreed method and provider capability

Follow the payment method, account and terms agreed for the trade. A provider such as Wise can support multiple transfer types; its name alone does not establish that a proposed payment matches National Bank Transfer or another selected method. Clarify compatibility rather than authorizing a substitution automatically.

Before accepting an offer, ask the provider for the current conditions and limits of the exact account, method, currency and destination. No account guarantees unrestricted transfers. Check that the complete payment can arrive within the agreed time. If a daily limit turns out too low, explain it in trade chat before changing the schedule or sending installments. If the peer is unresponsive or the schedule cannot be met, request mediation through that protocol's support flow. A historical two-installment resolution is not universal permission to split payments.

## Market price discrepancies

Before committing, compare the offer's actual fiat and BTC amounts rather than relying only on a displayed premium/discount percentage. If the reference price differs substantially from other current references, record currency, time, application version and the values observed and report the discrepancy through established support. A restart or an old message that a report was forwarded does not prove the feed is correct or a fix is in progress. Do not make an unchecked trade merely because its displayed percentage looks favorable.

## Historical execution price and margin

Use stored trade data to audit a historical price, not a current market query. The reviewed Bisq Easy desktop history shows and exports price, percentage and pricing mode, calculating the percentage against the market price stored in the contract. Bisq 1 closed-trade history exports execution price and the stored deviation for market-relative offers. Confirm the product, release and trade, then compare actual fiat divided by BTC with its recorded terms. A single exchange can differ from Bisq’s reference; current Binance prices and rounded amounts do not establish an exact historical quote or prove that both clients had identical quotes.

## Offer matching is not payment duration

There is no verified universal average wait time for finding an Amazon eGift-card seller. Finding a seller depends on current offers, amount, currency and payment terms; a trade’s payment period is not an estimate of how long matching takes. Inspect the current offerbook and compare actual quoted prices without assuming a required premium. Before buying a card, verify the applicable Amazon region and terms and the seller’s agreed payment requirements; an available Bisq offer does not waive issuer restrictions.

## Evidence / Sources

- [Trading rules](https://bisq.wiki/Trading_rules): agreed details, provider limits and payment timing for Bisq 1.
- [Bisq Easy](https://bisq.wiki/Bisq_Easy): explicit trade terms, review of amounts and mediation through the trade chat for Easy.
- [Payment methods](https://bisq.wiki/Payment_methods): method/provider differences; payments occur outside the software.
- Reviewed price-report evidence supports collecting actual amounts and incident details; it did not establish a diagnosis or fix.

- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/apps/desktop/desktop/src/main/java/bisq/desktop/main/content/bisq_easy/history/BisqEasyTradeHistoryListItem.java
- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/apps/desktop/desktop/src/main/java/bisq/desktop/main/content/bisq_easy/history/BisqEasyHistoryView.java
- https://github.com/bisq-network/bisq/blob/8b381bfb45edd3912f2082d5af0db1dac9ceed43/desktop/src/main/java/bisq/desktop/main/portfolio/closedtrades/ClosedTradesView.java
- https://bisq.wiki/Bisq_Price_Indices
- https://bisq.wiki/Amazon_eGift_card
- https://digprjsurvey.amazon.co.uk/csad/help/node/GNG9PXYZUMQT72QK

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 1089, 1848. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

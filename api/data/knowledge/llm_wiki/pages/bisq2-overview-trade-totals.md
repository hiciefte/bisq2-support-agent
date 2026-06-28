---
id: bisq2-overview-trade-totals
title: Bisq 2 overview totals, trade history, and stale notifications
type: llm_wiki
page_type: known_issue
status: reviewed
protocol: bisq_easy
reviewed_by: suddenwhipvapor
reviewed_at: '2026-06-27'
risk_level: low
source_refs:
- wiki:Bisq 2
- wiki:Bisq Easy
- faq:77
- faq:708
- faq:869
---
## Canonical Support Answer

If the user asks about the value presented by Bisq 2 overview totals in their profile, explain that those statistics only refer to the total amounts currently being offered in the offer book, and do not represent the total value bought or sold in past trades.

If the completed-trade history under Bisq Easy > Trade History tab looks incomplete, explain that Bisq Easy is centered around data privacy, so unless the trade flow was completed correctly, the trade will not show in the history.

If the issue is a stale open-trade badge or ghost notification after a trade was completed outside the app and both parties received what they expected, clearing notifications or rejecting/canceling the completed stale trade entry can be appropriate. If fiat or BTC delivery is still unresolved, do not clear the UI state as a fix; use trade chat and mediation/support.

For tax/accounting requests, explain that Bisq Easy may not provide a complete CSV/reporting export by design. Users should keep their own records for completed trades when they need external accounting.

## Applies When

- The user says the Bisq 2 overview shows zero buying/selling totals after completed trades.
- The user asks why historical Bisq Easy volume or totals are not aggregated.
- The user is concerned that completed Bisq Easy trades vanished from the overview.
- The user has trade notifications or badges but no visible unresolved trade.
- The user asks for a CSV/export of past Bisq Easy trades.

## Do Not Say

- Do not say the user lost funds based only on zero overview totals.
- Do not claim that Bisq 2 keeps a complete global long-term trading history.
- Do not tell the user to create a new profile as a fix before checking the current profile and trade list.
- Do not clear stale notifications if the underlying trade is still unresolved.
- Do not mix this with Bisq 1 wallet balance or DAO-state troubleshooting.

## Evidence / Sources

- `wiki:Bisq 2` documents Bisq 2 privacy, multiple identities, and self-custodial local application context.
- `wiki:Bisq Easy` documents Bisq Easy profile/identity usage and trade flow.
- `faq:77` and `faq:708` cover completed/stale Bisq Easy trade cleanup.
- `faq:869` states that Bisq Easy does not provide a reporting CSV and users may need to keep their own records.

## Review Notes

- representation of "overview totals" was very wrong in the original guide

## Last Change Summary

Fixed the description of the scope for trade overview totals and removed redundant paragraphs.

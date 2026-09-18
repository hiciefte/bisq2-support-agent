---
id: bisq2-overview-trade-totals
title: Bisq 2 offer totals, local trade history and reporting
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: bisq_easy
reviewed_by: ai-review:codex:knowledge-batch-20260918
reviewed_at: '2026-09-18T08:30:52.377693+00:00'
risk_level: low
source_refs:
- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/apps/desktop/desktop/src/main/java/bisq/desktop/main/content/user/profile_card/overview/ProfileCardOverviewController.java
- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/apps/desktop/desktop/src/main/java/bisq/desktop/main/content/bisq_easy/history/BisqEasyHistoryController.java
- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/apps/desktop/desktop/src/main/java/bisq/desktop/main/content/bisq_easy/history/BisqEasyHistoryView.java
- https://bisq.wiki/Bisq_2
---
## Canonical Support Answer

First identify the exact screen. Profile-card overview buying/selling totals are computed from the profile's offers in the offer book; they are not lifetime completed-trade volume or a wallet balance. Zero overview totals alone do not indicate lost BTC or deleted trades.

Trade history is separate local application state. Current desktop source reads closed trades and supports filtering, trade details and exports. If history appears incomplete, check the selected profile, active versus closed trade state, filters, restored data and client version. Do not explain missing entries merely by saying privacy hides them, and do not create a new profile as a recovery step.

Current desktop source includes CSV export of history fields, including amounts, payment method and transaction information. Do not repeat the old categorical claim that Easy has no CSV by design. Check export availability in the installed release; source availability is not proof that every historical or mobile client has the same control. Keep your own records where needed and verify completeness. A local export is not a guaranteed complete global history or a tax assessment.

For ghost badges, verify there is no unresolved trade before clearing notifications. If either payment remains unresolved, retain the state and request mediation/support. If both sides settled but the UI did not, obtain version-appropriate cleanup guidance rather than canceling to conceal missing delivery.

A mediation count alone cannot establish a failure rate. That requires total trades for the same period, consistent definitions and resolved outcomes. Do not derive either near-perfect reliability or widespread failure from anecdotes or substitute Bisq 1 wallet-error counts for Easy disputes.

## Evidence / Sources

- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/apps/desktop/desktop/src/main/java/bisq/desktop/main/content/user/profile_card/overview/ProfileCardOverviewController.java
- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/apps/desktop/desktop/src/main/java/bisq/desktop/main/content/bisq_easy/history/BisqEasyHistoryController.java
- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/apps/desktop/desktop/src/main/java/bisq/desktop/main/content/bisq_easy/history/BisqEasyHistoryView.java
- https://bisq.wiki/Bisq_2

## Review Notes

Independently reviewed by the parent AI reviewer after individual candidate review. Reviewer: `ai-review:codex:knowledge-batch-20260918`. Sources checked on 2026-09-18; verify release-sensitive behavior against the user's installed version.

## Last Change Summary

Preserved offer-total semantics confirmed in source. Replaced obsolete no-CSV and privacy-causes-missing-history claims with version-qualified closed-trade/export guidance and added the denominator requirement for failure rates.

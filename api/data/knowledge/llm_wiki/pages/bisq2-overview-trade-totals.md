---
id: bisq2-overview-trade-totals
title: Bisq 2 overview totals and completed-trade history
type: llm_wiki
page_type: known_issue
status: reviewed
protocol: bisq_easy
reviewed_by: codex-initial-llm-wiki-review
reviewed_at: "2026-06-10"
risk_level: low
source_refs:
  - support:matrix_eval_029
  - wiki:Bisq 2
  - wiki:Bisq Easy
---
## Canonical Support Answer

If the Bisq 2 overview shows zero total buying or selling even though trades were completed, do not assume the trades disappeared or that funds are missing. Bisq 2 is privacy-oriented and its overview totals may reflect limited current-profile or current-session state rather than a complete long-term trade history.

Ask the user to check the relevant Bisq Easy profile/identity and the trade list for the completed trades. If the individual completed trades are visible, explain that the overview totals can be limited or reset by profile/session/history scope. If completed trades are not visible under the expected profile, treat it as a profile/data-directory recovery question instead of a balance-loss question.

## Applies When

- The user says the Bisq 2 overview shows zero buying/selling totals after completed trades.
- The user asks why historical Bisq Easy volume or totals are not aggregated.
- The user is concerned that completed Bisq Easy trades vanished from the overview.

## Do Not Say

- Do not say the user lost funds based only on zero overview totals.
- Do not claim that Bisq 2 keeps a complete global long-term trading history.
- Do not tell the user to create a new profile as a fix before checking the current profile and trade list.
- Do not mix this with Bisq 1 wallet balance or DAO-state troubleshooting.

## Evidence / Sources

- `support:matrix_eval_029` captures a reviewed support case where zero overview totals after completed trades were explained as limited history/profile context.
- `wiki:Bisq 2` documents Bisq 2 privacy, multiple identities, and current Bisq Easy scope.
- `wiki:Bisq Easy` documents Bisq Easy profile/identity usage and trade flow.

## Review Notes

- Verify exact current UI labels for overview totals and completed-trade history before giving click-by-click instructions.

## Last Change Summary

Added after RAGAS showed an uncovered Bisq 2 overview trade-total question with irrelevant retrieved context.

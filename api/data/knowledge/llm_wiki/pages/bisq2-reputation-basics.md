---
id: bisq2-reputation-basics
title: Bisq Easy reputation, profile identity and Bisq 1 proofs
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: bisq_easy
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: medium
source_refs:
- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/bisq-easy/src/main/java/bisq/bisq_easy/BisqEasyTradeAmountLimits.java
- https://bisq.wiki/Reputation
- https://bisq.wiki/Bisq_Easy
- https://bisq.wiki/Backup
- https://bisq.wiki/Reputation#Method_3:_Importing_Bisq_1_Account_Age
- https://bisq.wiki/Reputation#Method_4:_Importing_Bisq_1_Signed_Account_Age
---
## Canonical Support Answer

Buyers do not need reputation to buy BTC on Bisq Easy. They assess the seller because they pay before receiving BTC. Seller reputation influences permitted offer amounts and buyer trust, but is not proof that a trade will succeed.

Completing trades does not earn this reputation. Supported sources include BSQ burns, BSQ bonds, Bisq 1 account age and Bisq 1 signed-account-age evidence. Account age and signed account age are separate sources; use eligible existing proofs through the current Reputation workflow. Do not invent points for trading, community activity or a public completed-trade count.

The workflow binds evidence to the chosen Bisq 2 profile identity. Follow the in-app instructions, including the intended profile ID, before a burn or bond; these actions have financial consequences. Reputation from an old profile is not inherited by a newly created one. Recovering the original local identity is different from transferring reputation to another identity.

If reputation seems missing after an update or inactivity, confirm the selected profile and data directory, allow network data to synchronize and inspect preserved backups before assuming loss. A changing star rating is not necessarily lost points: the documented stars compare active profiles. Current rules, eligible amounts and score formulas must be checked against the installed supported release, not an old default threshold.

Bisq 1 account-age and signing imports convey reputation evidence, not its payment-account files, wallet, seed or open trades. Do not import a Bisq 1 backup into Bisq 2 or copy its keys there. Start from the Bisq 2 Reputation instructions and the eligible Bisq 1 account. A buyer does not need to install Bisq 1 merely to use Easy.

## Current-source seller capacity

In the current upstream Bisq Easy source reviewed on 2026-09-18 (commit ae3176e4431eeaef309aada264ff8a75616f21d7), creating a sell offer requires at least 1,200 reputation points. The score-based USD capacity is the reputation score divided by 200, rounded to whole USD and capped at 600 USD; the minimum trade amount is the equivalent of 6 USD. Thus 800 points corresponds to 4 USD and is below the minimum needed to create a sell offer. Offer validation also applies conversion, rounding and a 5% reputation tolerance in specified checks; that tolerance does not replace the 1,200-point create-sell-offer gate. Check the installed release and displayed limits, since current source does not prove identical behavior in every historical client. These are reputation points, not a BSQ amount or a recommendation to burn more. Reputation may come from eligible account-age proofs as well as burns or bonds. Use the current in-app reputation simulation and fee display before deciding whether to spend funds; a BSQ purchase amount, transaction fee and reputation score are different quantities.

## Do Not Say

- Do not claim burning is the only reputation mechanism or that all sellers must burn BSQ.
- Do not promise that reputation, age or signing guarantees honesty.
- Do not apply a Bisq 1 payment-account export as a full Bisq 2 migration.
- Do not spend funds based on an unverified fixed score-to-trade-amount formula.

## Import completion and authorization

There is no guaranteed import latency in the official account-age instructions. Use the proof for the intended Bisq 2 profile, paste the complete JSON into the matching import screen and request authorization. Check authorization feedback, profile selection and network synchronization; filling the fields alone does not complete the import. If unchanged, supply versions and redacted status/errors to support. The UI copy controls can help select the right content, but correct keyboard paste is not documented as causing delays. Trades do not earn these reputation points.

## Evidence / Sources

- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/bisq-easy/src/main/java/bisq/bisq_easy/BisqEasyTradeAmountLimits.java

- https://bisq.wiki/Reputation
- https://bisq.wiki/Bisq_Easy
- https://bisq.wiki/Backup

- https://bisq.wiki/Reputation#Method_3:_Importing_Bisq_1_Account_Age
- https://bisq.wiki/Reputation#Method_4:_Importing_Bisq_1_Signed_Account_Age

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 1372. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

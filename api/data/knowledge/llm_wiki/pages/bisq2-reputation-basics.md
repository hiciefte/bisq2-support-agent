---
id: bisq2-reputation-basics
title: Bisq Easy reputation basics
type: llm_wiki
page_type: support_playbook
status: proposed
protocol: bisq_easy
reviewed_by: null
reviewed_at: null
risk_level: medium
source_refs:
  - wiki:Reputation
  - wiki:Reputation2
  - wiki:Bisq Easy
  - faq:9
  - faq:17
  - faq:20
  - faq:28
  - faq:40
  - faq:65
  - faq:71
  - faq:86
  - faq:703
  - faq:1177
  - faq:1045
  - faq:1056
  - faq:1066
---
## Canonical Support Answer

Bisq Easy uses seller reputation as its main safety mechanism. Buyers do not need reputation to buy BTC; buyers evaluate the seller's reputation because the buyer sends fiat before receiving bitcoin. Sellers need reputation to make attractive offers and to access larger trade amounts.

A completed Bisq Easy trade does not automatically create reputation. Reputation can be built through the supported reputation mechanisms such as burning BSQ, bonding BSQ, importing a signed account witness, or importing account age from Bisq 1. Support should not invent additional reputation sources.

Reputation is tied to the Bisq 2 profile identity where it was created or imported. It is not a general account balance that can be freely transferred between profiles. If reputation appears missing, first confirm the user is using the correct profile, let network data finish syncing, and check local backups/profile data before assuming reputation is lost.

Seller trade limits and buyer visibility depend on current reputation rules and client settings. If a user asks how much they can sell, explain the principle first: higher verified reputation allows larger Bisq Easy selling capacity and makes offers more attractive to buyers. Quote exact minimum scores, star mapping, or trade-size formulas only after checking current Bisq 2 documentation/version.

Bisq 1 can still matter for reputation because account age or signed-account information can be imported, but Bisq 1 is not required just to start as a Bisq Easy buyer. Do not present Bisq 1 payment-account import as a wallet/account migration into Bisq 2; it is reputation-related information, not transfer of the Bisq 1 wallet or open trades.

## Applies When

- The user asks why reputation is needed in Bisq Easy.
- The user asks whether buyers need reputation.
- The user asks whether completing trades earns reputation.
- The user asks whether they need reputation when they cannot run Bisq 1 yet.
- The user asks whether Bisq Easy can be used before setting up Bisq 1.
- The user asks how to build, import, or check reputation.
- The user reports missing reputation after inactivity, update, restore, or profile switch.
- The user asks about seller reputation thresholds, stars, or maximum trade amount.

## Do Not Say

- Do not say reputation is earned by simply completing trades.
- Do not say reputation can be transferred to another profile.
- Do not treat Bisq 1 account age/signing as a Bisq 2 payment-account migration; it is imported for reputation.
- Do not imply Bisq 1 is required before a buyer can make a basic Bisq Easy BTC purchase.
- Do not quote exact reputation thresholds or trade-limit formulas without checking current client/version docs.
- Do not treat profile/data-directory recovery problems as reputation-policy problems.

## Evidence / Sources

- `wiki:Reputation` explains reputation as the Bisq Easy security model and lists build methods.
- `wiki:Reputation2` documents reputation thresholds, stars, and trade-limit concepts.
- `wiki:Bisq Easy` states reputation is seller-side security and buyers do not need reputation.
- `faq:9`, `faq:65`, `faq:71`, `faq:1056`, and `faq:1066` cover valid reputation methods and reputation display.
- `faq:17`, `faq:86`, `faq:1045`, and `faq:1177` cover profile-bound reputation and recovery checks.
- `faq:20`, `faq:28`, and `faq:40` explain why seller reputation matters economically and for buyer safety.

## Review Notes

- Confirm whether mobile/remote reputation UX has changed before giving version-specific mobile instructions.
- Production candidates about network bootstrapping, PGP signatures, Revolut, mobile pairing, and general Bisq 2 installation were intentionally excluded from this reputation page.

## Last Change Summary

Curated reputation candidates into a focused page covering buyer/seller roles, valid reputation mechanisms, profile binding, missing reputation checks, and current-limit caution.

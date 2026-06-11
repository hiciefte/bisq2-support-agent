---
id: bisq2-reputation-basics
title: Bisq Easy reputation basics
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: bisq_easy
reviewed_by: codex-initial-llm-wiki-review
reviewed_at: "2026-05-13"
risk_level: medium
source_refs:
  - wiki:Reputation
  - wiki:Bisq Easy
  - faq:9
  - faq:17
  - faq:71
  - faq:1045
  - faq:1056
  - faq:1066
---
## Canonical Support Answer

Bisq Easy uses seller reputation as its main safety mechanism. Buyers do not need reputation to buy BTC, because the buyer sends fiat first and the seller's reputation is the trust signal. Sellers need reputation to make attractive offers and to access larger trade amounts.

If a user asks whether they need reputation and cannot run Bisq 1 yet, answer that a buyer can still use Bisq Easy to buy BTC without having reputation or a Bisq 1 setup. Bisq 1 can become useful later for importing account age or using additional markets, but it is not required just to start as a Bisq Easy buyer.

Reputation can be built by burning BSQ, bonding BSQ, importing a signed account witness, or importing account age from Bisq 1. Reputation is tied to the profile identity where it was created or imported; it is not a general account balance that can be freely moved between profiles.

If reputation appears missing, first confirm the user is on the correct profile and allow time for network data to sync. If a BSQ burn or bond was performed and still does not appear after the expected wait, ask for the relevant non-sensitive profile and transaction details and hand off to support.

## Applies When

- The user asks why reputation is needed in Bisq Easy.
- The user asks whether buyers need reputation.
- The user asks whether they need reputation when they cannot run Bisq 1 yet.
- The user asks whether Bisq Easy can be used before setting up Bisq 1.
- The user asks how to build, import, or check reputation.
- The user reports missing reputation after inactivity, update, or restore.

## Do Not Say

- Do not say reputation is earned by simply completing trades.
- Do not say reputation can be transferred to another profile.
- Do not treat Bisq 1 account age/signing as a Bisq 2 payment account migration; it is imported for reputation.
- Do not imply Bisq 1 is required before a buyer can make a basic Bisq Easy BTC purchase.

## Evidence / Sources

- `wiki:Reputation` explains reputation as the Bisq Easy security model and lists build methods.
- `wiki:Bisq Easy` states reputation is seller-side security and buyers do not need reputation.
- `faq:9`, `faq:71`, and `faq:1056` list the valid ways to gain reputation.
- `faq:17` states reputation is tied to the profile.
- `faq:1045` and `faq:1066` describe where users can check reputation.

## Review Notes

- Confirm whether mobile/remote reputation UX has changed before giving version-specific mobile instructions.

## Last Change Summary

Converted from generated support playbook into internal LLM Wiki page; ready for local support-admin review.

---
id: bisq2-wallet-lightning-onchain
title: Bisq 2 wallet, Lightning, and on-chain receiving
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: bisq_easy
reviewed_by: codex-initial-llm-wiki-review
reviewed_at: "2026-05-13"
risk_level: low
source_refs:
  - wiki:Bisq 2 Wallet
  - wiki:Bisq Easy
  - wiki:Trade Protocols
  - faq:23
  - faq:55
  - faq:56
  - faq:75
  - faq:81
  - faq:691
---
## Canonical Support Answer

Bisq 2 does not include the built-in Bitcoin wallet that Bisq 1 has. In Bisq Easy, users provide an external Bitcoin wallet or invoice/address for receiving BTC. Bisq 2 also does not provide an integrated Lightning wallet.

For most Bisq Easy users who want normal bitcoin custody and a first UTXO for later Bisq 1 use, on-chain receiving is the default recommendation. Lightning can be used only when the buyer and seller intentionally agree on that payment route and the buyer has an external Lightning wallet/invoice.

If the user accidentally selected Lightning but wanted on-chain Bitcoin, they should immediately tell the counterparty in trade chat and provide the correct on-chain address before the seller sends BTC.

## Applies When

- The user asks whether Bisq 2 has a built-in BTC or Lightning wallet.
- The user asks whether to choose on-chain or Lightning.
- The user selected the wrong receive method in a Bisq Easy trade.
- The user compares Bisq 1 wallet behavior to Bisq 2.

## Do Not Say

- Do not say Bisq 2 currently manages an internal BTC wallet like Bisq 1.
- Do not say Bisq 2 can create or custody a Lightning wallet.
- Do not advise changing payment details silently; tell the user to coordinate in trade chat.

## Evidence / Sources

- `wiki:Bisq 2 Wallet` says Bisq 2 initially has no integrated BTC or BSQ wallet and users use their own wallet.
- `wiki:Bisq Easy` describes seller-paid on-chain mining fees or Lightning routing fees after fiat receipt.
- `wiki:Trade Protocols` distinguishes current Bisq Easy from future Lightning-related protocols.
- `faq:23`, `faq:55`, and `faq:56` confirm there is no built-in Lightning/Bisq 1-style wallet in Bisq 2.
- `faq:75` and `faq:81` cover wrong receive-method selection and on-chain default guidance.

## Review Notes

- Re-check this playbook before future wallet or Lightning protocol releases.

## Last Change Summary

Converted from generated support playbook into internal LLM Wiki page; ready for local support-admin review.

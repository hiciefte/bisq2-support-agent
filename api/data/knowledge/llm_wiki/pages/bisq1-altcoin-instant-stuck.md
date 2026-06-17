---
id: bisq1-altcoin-instant-stuck
title: "Deprecated: Bisq 1 Altcoin Instant trade protocol not progressing"
type: llm_wiki
page_type: support_playbook
status: deprecated
protocol: multisig_v1
reviewed_by: null
reviewed_at: null
risk_level: high
source_refs:
  - wiki:Dispute Resolution in Bisq 1
  - wiki:Mediation
  - wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees
  - wiki:Deposit transaction
---
## Canonical Support Answer

This page is deprecated before activation. Do not promote it as a standalone LLM Wiki page.

Altcoin Instant is not a separate support flow for stuck Bisq 1 trades. Use `bisq1-deposit-confirmed-stuck` when the deposit transaction exists but the app or protocol state is not progressing. Use `bisq1-failed-trade-fees` when the maker/taker/deposit transaction is missing or invalid. Use `bisq1-dispute-mediation-arbitration` when fiat/altcoin payment, locked funds, or peer cooperation requires mediation or arbitration.

## Applies When

- A generated candidate incorrectly targets this page.
- A reviewer sees an Altcoin Instant stuck-trade proposal and needs the canonical target page.

## Do Not Say

- Do not add new support guidance to this page.
- Do not treat Altcoin Instant as a special stuck-trade mechanism beyond its shorter trade period.
- Do not preserve duplicate guidance here when a broader Bisq 1 stuck-trade page already covers the case.

## Evidence / Sources

- `wiki:Dispute Resolution in Bisq 1` documents trader chat, mediation, and arbitration paths.
- `wiki:Mediation` documents mediator transaction checks and proof collection.
- `wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees` distinguishes failed transaction cases.
- `wiki:Deposit transaction` explains deposit txid verification.

## Review Notes

- Deprecated after production candidate review showed this page attracted unrelated stuck-trade, deposit, and mediation proposals.
- Keep the replacement guidance in `bisq1-deposit-confirmed-stuck`, `bisq1-failed-trade-fees`, and `bisq1-dispute-mediation-arbitration`.

## Last Change Summary

Deprecated before activation to prevent duplicate and misleading LLM Wiki review work.

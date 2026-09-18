---
id: bisq1-bsq-swaps
title: "Bisq 1 atomic BSQ swaps \u2014 separate from multisig trades and Bisq Easy"
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: all
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: medium
source_refs:
- wiki:BSQ swaps
- wiki:Trading BSQ
- wiki:Troubleshooting network issues
- wiki:Resyncing SPV file
- https://bisq.wiki/BSQ_swaps#Transaction_structure
- https://bisq.wiki/DAO_technical_overview#BSQ_token
- https://bisq.wiki/Trading_BSQ
---
## Strict scope

This page applies only to the atomic BTC/BSQ swap workflow in Bisq 1. It does not describe conventional multisig fiat trades, Bisq Easy, or a future MuSig protocol.

## Swap accounts and fees

Use the built-in BSQ swap workflow; no separate altcoin payment account is needed. A disabled form still needs its exact validation message and version checked—it is not explained by a missing BSQ payment account.

The swap exchanges BTC and BSQ in one transaction. It uses BTC mining fees and BSQ trading fees accounted for in its input/output structure. A BSQ seller's input must cover the BSQ sale and relevant BSQ fee; do not assume an entire displayed output is freely tradable. The BSQ seller does not need a separate BTC input merely to fund their part of that swap. Review the actual fees and change rather than importing a fixed ordinary-trade BSQ discount.

Unlike conventional Bisq 1 offers, a swap offer does not publish a maker-fee transaction on creation; proof of work provides offer spam resistance. The swap transaction's mining fee is determined when it is taken, not guaranteed at offer-creation time. Both peers must be online. Swaps do not use conventional multisig deposits or its mediation/arbitration payout mechanism.

## Timeouts and wallet state

For a repeated swap timeout, first check startup completion, network connections, peer availability and whether multiple offers/peers are affected. A timeout is not proof of wallet corruption. If Tor connectivity is faulty, use Bisq's documented built-in outdated-Tor-files cleanup in Network Info/Tor settings, then restart and wait for connections. Preserve identity/data; do not delete the directory.

If a swap transaction has left the wallet view inconsistent, verify its actual network state before applying documented SPV repair. Do not start a conventional escrow dispute or send an extra payment based solely on a timeout. Report the version, exact error and transaction status to verified support if unresolved.

## Quote units, net proceeds and burning

Read the displayed units: a price stated as BTC for 1 BSQ is the BTC amount per BSQ; compare the actual BTC and BSQ amounts in the confirmation screen. A higher headline price does not guarantee a small offer will be taken—compare net amounts after the displayed fees, and do not infer another trader’s motives. In an atomic BSQ swap, BTC mining fees and BSQ trading fees are accounted for in the swap’s inputs and outputs, rather than applying the ordinary fiat-trade fee recipe. Deliberately burning BSQ for a trading fee or proof-of-burn transaction removes its token value under DAO rules; the underlying satoshis contribute to Bitcoin mining fees rather than disappearing from Bitcoin. Burning is not a guarantee that remaining BSQ rises in market price.

## Evidence / Sources

- [BSQ swaps](https://bisq.wiki/BSQ_swaps): native account flow, atomic transaction, asymmetric inputs, offer proof of work and separate dispute semantics.
- [Trading BSQ](https://bisq.wiki/Trading_BSQ): built-in swap acquisition and separation from legacy altcoin account trading.
- [Troubleshooting network issues](https://bisq.wiki/Troubleshooting_network_issues): supported Tor recovery.
- [Resyncing SPV file](https://bisq.wiki/Resyncing_SPV_file): local wallet-chain repair, not a network confirmation guarantee.

- https://bisq.wiki/BSQ_swaps#Transaction_structure
- https://bisq.wiki/DAO_technical_overview#BSQ_token

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 1113. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

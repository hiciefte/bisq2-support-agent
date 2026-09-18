---
id: bisq2-wallet-lightning-onchain
title: Bisq Easy external wallets, Lightning and on-chain receiving
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: bisq_easy
reviewed_by: ai-review:codex:knowledge-batch-20260918
reviewed_at: '2026-09-18T08:30:52.377693+00:00'
risk_level: medium
source_refs:
- https://bisq.wiki/Bisq_2_Wallet
- https://bisq.wiki/Bisq_Easy
---
## Canonical Support Answer

Bisq Easy uses your external Bitcoin wallet; it does not provide the Bisq 1 internal BTC/BSQ wallet or an integrated Lightning wallet. There is no Bisq Easy Funds > Receive Funds balance to deposit into or withdraw from. An exchange withdrawal goes to a receiving address in your own wallet. Using a Bisq 1 wallet is one possibility, not a requirement.

During a purchase, the buyer provides the receiving address or agreed Lightning invoice in the trade flow and pays the seller using the agreed payment method. The seller sends BTC after verifying actual payment receipt. The buyer does not need to send BTC to Bisq to buy their first BTC; Bisq Easy has no BTC security deposit.

Choose a receiving method that meets the purpose of the trade. If you need an on-chain UTXO, for example to fund a Bisq 1 trade, receive on-chain BTC. A Lightning balance or invoice is not an on-chain address. Use Lightning only when both peers agree and have compatible functioning wallets; do not assume a named wallet currently offers every Lightning feature.

If the address is missing, ask the buyer to confirm it in the affected trade chat and verify the chosen network and settlement method. Before sending, check actual fiat receipt and whether BTC has already been sent. Do not infer an address from a Bisq 1 deposit transaction. If the interface or payment details disagree, involve support or mediation rather than send twice.

If Lightning was selected accidentally, contact the peer before any BTC is sent and agree the correct receiving method and any fee implications. Do not silently replace payment details or infer that a different network requires an automatic reduction in the agreed BTC amount.

## Do Not Say

- Do not invent an internal Bisq Easy receive, send or seed-recovery screen.
- Do not say buying requires a pre-existing BTC deposit.
- Do not treat an invoice as an on-chain address or promise recovery by changing a destination after sending.

## Evidence / Sources

- https://bisq.wiki/Bisq_2_Wallet
- https://bisq.wiki/Bisq_Easy

## Review Notes

Independently reviewed by the parent AI reviewer after individual candidate review. Reviewer: `ai-review:codex:knowledge-batch-20260918`. Sources checked on 2026-09-18; verify release-sensitive behavior against the user's installed version.

## Last Change Summary

Consolidated external-wallet questions and missing-address cases. Preserved on-chain/Lightning choice and coordination while removing internal-wallet and mandatory Bisq 1 receiving claims.

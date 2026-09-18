---
id: bisq1-transaction-privacy
title: Bisq 1 Bitcoin transaction links and deposit privacy
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
risk_level: medium
reviewed_by: ai-review:codex:knowledge-batch-20260918
reviewed_at: '2026-09-18T08:30:52.377693+00:00'
source_refs:
- https://bitcoin.org/en/protect-your-privacy
- https://bisq.wiki/Security_deposit
---
## Canonical Support Answer

Knowing one Bitcoin address does not by itself reveal every address derived by a wallet. Bitcoin transaction history is public, however: reused addresses, spending earlier outputs and combining inputs can connect addresses and trades. A new receiving address does not guarantee unlinkability.

In Bisq 1, the deposit holds the trade funds and both security deposits; the later payout is a different transaction stage. That public transaction chain can connect a buyer's deposit funding to the BTC received. If a funding source is already associated with an identity, buying without KYC does not erase the association.

Tor protects aspects of network communication, not those on-chain transaction links. Do not claim that Bisq trades, fresh addresses or arbitration payouts are absolutely anonymous. Keep identifying trade details and wallet information out of public channels.

## Evidence / Sources

- https://bitcoin.org/en/protect-your-privacy
- https://bisq.wiki/Security_deposit

## Review Notes

Independently reviewed by the parent AI reviewer after individual candidate review. Reviewer: `ai-review:codex:knowledge-batch-20260918`. Sources checked on 2026-09-18; verify release-sensitive behavior against the user's installed version.

## Last Change Summary

Preserved the reviewed address-derivation and funding-linkage distinction while correcting multisig deposit versus payout terminology.

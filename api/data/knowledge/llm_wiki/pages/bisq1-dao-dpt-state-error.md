---
id: bisq1-dao-dpt-state-error
title: Bisq 1 DAO state and delayed payout transaction mismatch errors
type: llm_wiki
page_type: support_playbook
status: proposed
protocol: multisig_v1
reviewed_by: null
reviewed_at: null
risk_level: medium
source_refs:
  - wiki:BuyerVerifiesPreparedDelayedPayoutTx Exception error
  - wiki:Arbitration
  - wiki:DAO technical overview
  - wiki:Phase zero
  - wiki:Payment account age witness
  - wiki:Troubleshooting network issues
  - faq:1163
  - faq:1198
  - faq:1162
  - faq:1165
---
## Canonical Support Answer

Errors such as `BuyerVerifiesPreparedDelayedPayoutTx`, delayed payout transaction mismatch, `snapshot height doesn't match`, or repeated DAO-state warnings usually mean the local Bisq DAO state needs to be checked before the user continues trading. A common reason is that one peer has stale or inconsistent DAO state, which can cause peers to construct different delayed payout transactions.

The user should check DAO network status/DAO network monitor and confirm whether their DAO state is in consensus with seed nodes. The safest local corrective step is the built-in rebuild/resync DAO state from resources option in settings/preferences. This is different from SPV resync: DAO resync rebuilds Bisq DAO state, while SPV resync rebuilds wallet-chain state.

If the local user's DAO state is correct but the peer is out of sync, the local user may not be able to fix the trade alone. Collect the exact error, trade ID, relevant transaction IDs, DAO/network status screenshots, and involve support/mediation if a trade is affected.

Temporary seed-node workarounds such as explicit `--seedNodes` or `--bannedSeedNodes` should be treated as incident-specific and advanced. Use them only when the source/current incident supports that advice, and remove temporary overrides afterward. For normal user support, prefer the built-in DAO rebuild/resync path first.

If a failed trade has no valid deposit transaction, use the failed-trade page for the funds/fees question and this page only for the DAO/DPT diagnosis.

## Applies When

- The user reports `BuyerVerifiesPreparedDelayedPayoutTx`.
- The user reports delayed payout transaction mismatch.
- The user sees `snapshot height doesn't match` when taking an offer.
- The user gets repeated prompts to resynchronize DAO state.
- The user asks why trade protocol setup fails before normal payment flow.
- The user asks whether DAO state can affect failed trades or delayed payout transaction construction.
- The user asks about temporary seed-node/ban workarounds for DAO-state incidents.

## Do Not Say

- Do not describe this as a normal payment-account age witness problem unless the actual error says that.
- Do not advise deleting DAO data manually before using the built-in rebuild/resync option.
- Do not promise that rebuilding local DAO state fixes errors caused by the peer.
- Do not confuse DAO resync with SPV wallet resync.
- Do not publish hard-coded seed-node onion addresses as generic evergreen advice.
- Do not tell users that funds are locked or lost before checking whether a valid deposit transaction exists.

## Evidence / Sources

- `wiki:BuyerVerifiesPreparedDelayedPayoutTx Exception error` explains DPT mismatch and DAO state consensus.
- `wiki:Arbitration` explains why delayed payout transactions exist in the Bisq 1 dispute protocol.
- `wiki:DAO technical overview` and `wiki:Phase zero` document DAO-state validation context.
- `wiki:Troubleshooting network issues` covers network instability that can affect sync.
- `faq:1163` and `faq:1198` cover rebuilding DAO state from resources.
- `faq:1162` and `faq:1165` cover DAO sync effects on BSQ balances and repeated DAO sync warnings.

## Review Notes

- Confirm current Bisq 1 menu labels for DAO-state rebuild before giving exact navigation.
- Keep seed-node advice incident-specific; stale onion addresses should not become permanent support guidance.

## Last Change Summary

Expanded DAO/DPT guidance to include snapshot-height errors, DAO-vs-SPV distinction, peer-state limits, and temporary seed-node workaround caution.

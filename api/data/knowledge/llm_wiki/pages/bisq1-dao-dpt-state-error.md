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
---
## Canonical Support Answer

Errors such as `BuyerVerifiesPreparedDelayedPayoutTx` or delayed payout transaction mismatch usually indicate that the peers are not constructing the same delayed payout transaction. A common reason is that one peer has an incorrect or stale DAO state.

The user should check the DAO network monitor and confirm their DAO state is in consensus with seed nodes. A safe local corrective step is to rebuild DAO state from resources in settings/preferences. If the other peer is the one with the wrong DAO state, the local user may not be able to fix that trade with local actions alone and may need to trade with a different peer or involve support.

## Applies When

- The user reports `BuyerVerifiesPreparedDelayedPayoutTx`.
- The user reports delayed payout transaction mismatch.
- The user asks why trade protocol setup fails before normal payment flow.

## Do Not Say

- Do not describe this as a normal payment-account age witness problem unless the actual error says that.
- Do not advise deleting DAO data manually before using the built-in rebuild option.
- Do not promise that rebuilding local DAO state fixes errors caused by the peer.

## Evidence / Sources

- `wiki:BuyerVerifiesPreparedDelayedPayoutTx Exception error` explains DPT mismatch and DAO state consensus.
- `wiki:Arbitration` explains why delayed payout transactions exist in the Bisq 1 dispute protocol.

## Review Notes

- Confirm current Bisq 1 menu labels for DAO-state rebuild before giving exact navigation.

## Last Change Summary

Converted from generated support playbook into internal LLM Wiki page; ready for local support-admin review.

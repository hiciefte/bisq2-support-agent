---
id: bisq1-dao-dpt-state-error
title: Bisq 1 DAO consensus and delayed-payout mismatch diagnosis
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: medium
source_refs:
- wiki:BuyerVerifiesPreparedDelayedPayoutTx Exception error
- wiki:DAO technical overview
- wiki:Arbitration
- wiki:Performance Tips
- wiki:Troubleshooting network issues
- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/desktop/src/main/java/bisq/desktop/main/presentation/DaoPresentation.java#L117-L143
- https://bisq.wiki/Performance_Tips
- https://bisq.wiki/DAO_technical_overview
---
## Canonical Support Answer

Bisq 1 uses DAO state during trade setup even when the user does not participate in governance. `BuyerVerifiesPreparedDelayedPayoutTx`, `TxIds of buyersPreparedDelayedPayoutTx and sellersPreparedDelayedPayoutTx must be the same`, and `snapshot height doesn't match` can arise when peers disagree on DAO state and construct different delayed payout transactions. DPT means delayed payout transaction, not the ordinary deposit or final trader payout.

Inspect `DAO > Network Monitor > DAO State` and local consensus with seed nodes. If local state is inconsistent, the built-in recovery is `Settings > Preferences > Rebuild DAO state from resources`. Allow it to finish. SPV resync repairs Bitcoin wallet-chain tracking; it is not DAO-state recovery. A UTXO conflict explicitly shown in DAO Network Monitor belongs to this diagnosis; a generic wallet spent-output error is not automatically a DAO problem.

A healthy local node can still encounter an out-of-sync peer. Another peer's disagreement alone does not prove that local state needs rebuilding. If a completed rebuild leaves the local node in consensus but the error persists, collect the version, state monitor evidence, exact error and affected peers/offers for verified support. Stop repeating paid trade attempts. Trading with a more expensive offer is not proof that the underlying problem is fixed.

For the DAO-needs-resync popup in the inspected Bisq 1 implementation, closing the warning does not clear its cause. After parsing completes and wallet/DAO heights match, a remaining seed-node conflict or disconnected DAO state chain can cause the popup to return after 30 seconds. Open DAO > Network Monitor > DAO State to inspect that condition. Matching height alone is not proof of matching consensus hashes. This behavior is version-specific; retain the exact warning and application version when seeking support.

## Funds, fees and offer state

Verify maker fee, taker fee and the actual deposit separately. No valid deposit means the trade amount and security deposits did not enter that trade's escrow, although fee transactions may have spent funds. Inspect BTC fees under Funds > Transactions and BSQ fee transactions in the DAO wallet. Use failed-trade guidance for verified missing deposits and fee reimbursement; do not infer lockup or entitlement from an error string.

For a BSQ-fee offer that deactivates, check fee-transaction existence/confirmation and DAO consensus independently. Bitcoin confirmation does not establish DAO interpretation, and a local DAO rebuild cannot create an absent fee transaction. DAO synchronization problems may prevent taking offers; do not promise that every offer disappears or that rebuilding automatically restores it.

## Startup, resource use and incident boundaries

A DAO page can be blank while loading. Observe the bottom synchronization status and actual progress before concluding it is stuck. DAO synchronization can use substantial CPU and make the interface sluggish; this should improve after completion. There is no fixed ten-minute completion deadline. For prolonged stalls, record progress, version, peer connectivity and relevant logs. A normal restart may help a stalled process; repeated blind rebuilds are not a diagnosis.

Temporary seed-node overrides or bans are incident-specific, not evergreen fixes. Verify the current incident and remove temporary overrides afterward. Do not embed remembered onion addresses or obsolete release numbers in advice. Do not replace the data directory or manually remove DAO stores merely because rebuilding failed.

The synchronization bar under DAO > BSQ Wallet > Transactions and relevant DAO block-height messages in bisq.log help distinguish advancing parsing from a stall. Compare successive observations before repeating a rebuild.

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 418, 1261, 1633. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Evidence / Sources

- [BuyerVerifiesPreparedDelayedPayoutTx Exception error](https://bisq.wiki/BuyerVerifiesPreparedDelayedPayoutTx_Exception_error): official procedure or scope referenced above.
- [DAO technical overview](https://bisq.wiki/DAO_technical_overview): official procedure or scope referenced above.
- [Arbitration](https://bisq.wiki/Arbitration): official procedure or scope referenced above.
- [Performance Tips](https://bisq.wiki/Performance_Tips): official procedure or scope referenced above.
- [Troubleshooting network issues](https://bisq.wiki/Troubleshooting_network_issues): official procedure or scope referenced above.

- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/desktop/src/main/java/bisq/desktop/main/presentation/DaoPresentation.java#L117-L143

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

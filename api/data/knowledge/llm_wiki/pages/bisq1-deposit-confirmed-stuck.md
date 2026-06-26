---
id: bisq1-deposit-confirmed-stuck
title: Bisq 1 deposit confirmed but trade appears stuck
type: llm_wiki
page_type: support_playbook
status: proposed
protocol: multisig_v1
reviewed_by: null
reviewed_at: null
risk_level: high
source_refs:
  - wiki:Deposit transaction
  - wiki:Resyncing SPV file
  - wiki:Troubleshooting wallet issues
  - wiki:Dispute Resolution in Bisq 1
  - wiki:Mediation
  - wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees
  - faq:855
  - faq:1116
  - faq:1137
  - faq:1175
---
## Canonical Support Answer

When a Bisq 1 trade is stuck at `Wait for blockchain confirmation`, first separate the blockchain state from Bisq's local wallet/protocol state. Open the trade details, copy the deposit transaction ID, and check it on a Bitcoin block explorer.

If the deposit transaction is confirmed on-chain but Bisq still shows zero confirmations or does not advance, perform an SPV resync from the Bisq interface and restart as prompted. After the resync, re-check the trade state, wallet balance, and trade details. In some cases the resync may need to complete fully before the UI reflects the confirmed deposit.

If the user is the buyer and the deposit transaction is confirmed but the UI has not advanced, do not blindly send fiat. Only proceed if the trade contract/details clearly show the seller's payment details and the user understands the trade is valid; otherwise ask for mediator/support review. If payment details are absent or inconsistent, keep the trade data intact and use trader chat or mediation.

If the deposit transaction is missing, `N/A`, invalid, or not found on-chain, use the failed-trade workflow instead. An SPV resync may still be useful to make the UI recognize the failed state, but a missing deposit transaction is not the same as a confirmed deposit stuck in the UI.

If the transaction is real but still unconfirmed in the mempool, the next step is usually waiting or advanced fee/CPFP analysis, not repeated SPV resync. If the symptom is generic wallet balance mismatch, many ghost UTXOs, or SPV resync repeatedly failing, use the wallet/data-directory recovery page.

DAO-state resync is only relevant when the error is explicitly DAO/DPT-related. Do not recommend DAO resync for ordinary wallet-chain display problems.

## Applies When

- The user says the deposit transaction is confirmed but Bisq still shows the trade stuck.
- The trade remains at `Wait for blockchain confirmation` even though a block explorer shows confirmations.
- Payment details or peer actions do not appear after deposit confirmation.
- The user needs to distinguish SPV wallet resync from DAO-state resync.
- The user asks whether they should delete or cancel a stuck confirmed-deposit trade.
- The user sees the deposit transaction as unconfirmed in Bisq but confirmed in the mempool/block explorer.

## Do Not Say

- Do not tell the user to delete local trade data.
- Do not treat a missing deposit txid and confirmed deposit txid as the same problem.
- Do not suggest DAO-state rebuild for a normal wallet-chain display issue unless the error is DAO specific.
- Do not bypass mediation when funds may be locked in multisig.
- Do not tell a buyer to send fiat if payment details are missing or the trade contract is unclear.
- Do not say funds are lost before checking the deposit transaction and wallet state.

## Evidence / Sources

- `wiki:Deposit transaction` explains locating and verifying the deposit txid.
- `wiki:Resyncing SPV file` and `wiki:Troubleshooting wallet issues` document SPV resync for missing transactions, incorrect balances, and stale wallet-chain state.
- `wiki:Dispute Resolution in Bisq 1` describes trader chat and mediation paths.
- `wiki:Mediation` documents mediator transaction checks and proof requests.
- `wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees` distinguishes failed/missing deposit transactions from valid deposits.
- `faq:855`, `faq:1116`, `faq:1137`, and `faq:1175` cover confirmed-on-chain but unrecognized deposits, missing/invalid transactions, and SPV resync outcomes.

## Review Notes

- Exact UI labels vary by Bisq 1 version; verify before giving click-by-click instructions.
- Production candidates with memory tuning, DAO sync, privacy, payout, and general wallet issues were intentionally routed to other pages instead of bloating this confirmed-deposit page.

## Last Change Summary

Cleaned the production-approved page by removing noisy appended refs and reducing it to a safe decision tree for confirmed deposit, missing deposit, pending mempool deposit, and SPV/mediation boundaries.

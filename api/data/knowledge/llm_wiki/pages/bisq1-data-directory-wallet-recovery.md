---
id: bisq1-data-directory-wallet-recovery
title: Bisq 1 data directory, wallet recovery, and moving installations
type: llm_wiki
page_type: support_playbook
status: proposed
protocol: multisig_v1
reviewed_by: null
reviewed_at: null
risk_level: high
source_refs:
  - wiki:Data directory
  - wiki:Backing up application data
  - wiki:Restoring application data
  - wiki:Switching to a new data directory
  - wiki:Create a new wallet for your data directory
  - wiki:Restoring your wallet from seed
  - wiki:Last resort restore
  - wiki:Emergency wallet
  - wiki:Troubleshooting wallet issues
  - wiki:Resyncing SPV file
  - wiki:Command line options
  - wiki:Bisq 2 Wallet
  - wiki:BSQ
---
## Canonical Support Answer

Bisq 1 account, wallet, trade, payment-account, dispute, age-witness, onion-address, and notification state is local application data. For a complete move to another computer, copy the full Bisq data directory while Bisq is closed, start the new installation from that copied directory, and stop using the old installation for that same wallet/state. Do not run or alternate the same data directory on two active installations because it can corrupt state in hard-to-debug ways.

A wallet seed can recover spendable on-chain BTC, but it does not restore the full Bisq application state. It does not by itself restore open trades, support tickets, trade history, payment accounts, account-age metadata, onion identity, or BSQ/DAO state. If the user needs the Bisq account/trade state, prioritize the newest full data-directory backup. If the user only needs BTC funds and normal Bisq recovery is blocked, use the documented seed-restore or emergency-wallet path, but explain clearly that this is wallet-funds recovery, not full Bisq-state recovery.

Use SPV resync for wallet-chain display problems such as incorrect balances, missing transactions, ghost UTXOs, or a transaction that is confirmed on-chain but not recognized by Bisq. SPV resync rebuilds local blockchain state from the Bitcoin network; it should not change the user's wallet keys or trade records, but the user should still make a backup first and should not interrupt the resync. If an old wallet has hundreds of transactions and SPV resync repeatedly becomes impractical, consider the documented new-wallet workflow only after confirming there are no open offers, open trades, mediations, arbitrations, or pending BSQ/DAO actions.

If Bisq cannot start or a restored data directory fails, do not delete files blindly. First make a copy of the current data directory, then try a clean restore from the newest full backup. If that fails, use the last-resort restore guide to copy only the documented files into a fresh data directory. Emergency-wallet tools should be treated as last-resort fund recovery and should be used only after support has confirmed that normal recovery is not suitable.

Running separate Bisq instances is possible only when they use separate data directories and separate wallets. Use documented command-line options such as `--appData` or `--appDataDir` when deliberately creating separate instances. Do not use this as a shortcut for sharing one wallet or one active set of offers across machines.

Bisq 1 and Bisq 2 are separate applications and trade protocols. Bisq 2 does not import the Bisq 1 built-in wallet or open Bisq 1 trades. Bisq 2 uses external wallets for Bisq Easy, while Bisq 1 remains the relevant application for Bisq 1 wallet, DAO, BSQ, and multisig-trade state.

BSQ is colored bitcoin recognized by the Bisq wallet. BSQ transfers and balances belong in the Bisq DAO/BSQ wallet flow, not in the normal BTC wallet balance. When moving BSQ between instances, preserve backups and use the documented Bisq wallet/DAO screens; do not send BSQ to arbitrary external BTC wallets or assume every displayed BSQ amount is spendable after dust/change constraints.

## Applies When

- The user asks how to move Bisq 1 from one computer, OS, or server to another.
- The user asks whether importing a seed or wallet backup restores trades, payment accounts, age, or history.
- The user has reinstalled Bisq and lost trade history, payment accounts, support tickets, or open-trade visibility.
- The user sees incorrect wallet balance, ghost UTXOs, missing transactions, or an SPV resync question.
- The user has an old wallet with many transactions and repeated SPV resync problems.
- The user wants to run multiple Bisq instances or separate data directories.
- The user asks whether Bisq 1 wallet/trade state can be used directly in Bisq 2.
- The user asks how to move or inspect BSQ balances between Bisq 1 instances.

## Do Not Say

- Do not say a wallet seed restores the complete Bisq application state.
- Do not tell users to run the same data directory on two active installations.
- Do not recommend deleting the data directory before a verified backup exists.
- Do not promise recovery of open trade state, payment accounts, or history when no current backup exists.
- Do not conflate Bisq 1 application data recovery with importing a Bisq 2 profile.
- Do not present emergency-wallet use as a routine troubleshooting step.
- Do not advise switching to a new wallet/data directory while open trades, offers, mediations, or arbitrations are active.
- Do not tell users to send BSQ to a normal external BTC wallet.

## Evidence / Sources

- `wiki:Data directory` documents where Bisq stores local application data.
- `wiki:Backing up application data` and `wiki:Restoring application data` cover full data-directory backup and restore.
- `wiki:Switching to a new data directory`, `wiki:Create a new wallet for your data directory`, and `wiki:Command line options` cover controlled migration and separate-instance workflows.
- `wiki:Restoring your wallet from seed`, `wiki:Last resort restore`, and `wiki:Emergency wallet` distinguish wallet-funds recovery from full application-state recovery.
- `wiki:Troubleshooting wallet issues` and `wiki:Resyncing SPV file` document SPV resync and wallet backup recovery.
- `wiki:Bisq 2 Wallet` documents that Bisq 2 initially uses external wallets rather than the Bisq 1 built-in wallet.
- `wiki:BSQ` documents BSQ as colored bitcoin recognized by Bisq software.

## Review Notes

- Verify exact OS-specific directory paths and menu labels against the user's version before giving path-level commands.
- Treat open trades and disputes as high risk: preserve backups first and route uncertain cases to support/mediation rather than improvising file deletion.
- Some production candidates about Start9, mobile pairing, XMR subaddresses, or general network failures were intentionally not added here because they need separate source-backed pages or are too environment-specific.

## Last Change Summary

Curated the production candidate cluster into one high-signal page for Bisq 1 data-directory moves, seed-restore limits, SPV resync, old-wallet migration, separate instances, Bisq 1/Bisq 2 boundaries, and BSQ wallet handling.

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
---
## Canonical Support Answer

Bisq 1 account, wallet, trade, payment-account, dispute, and age-witness data is local application data. A wallet seed can recover on-chain BTC wallet funds, but it does not by itself restore the full Bisq application state, open trades, support tickets, trade history, payment accounts, or account-age metadata. For a complete move to another machine, copy the full Bisq data directory from a current backup or from the old installation, then stop using the old installation to avoid split state or wallet corruption.

If the old data directory is damaged, restore from the newest full backup first. If that fails, use the last-resort restore approach and copy only the specific documented files needed for wallet, payment-account, and trade-state recovery. If the app starts but wallet balance or transactions look wrong after recovery, perform an SPV resync before concluding funds are missing.

If the user only needs to recover spendable BTC and the normal app recovery path is blocked, use the documented seed restore or emergency wallet path, but clearly explain that this is wallet-funds recovery, not full Bisq account/trade-state recovery.

## Applies When

- The user asks how to move Bisq 1 from one computer or OS to another.
- The user asks whether importing a seed or wallet backup restores trades, payment accounts, age, or history.
- The user has reinstalled Bisq and lost trade history, payment accounts, or support tickets.
- The user wants to create a fresh data directory but preserve funds or necessary account data.
- The user asks whether to run the same Bisq data on two machines.

## Do Not Say

- Do not say a wallet seed restores the complete Bisq application state.
- Do not tell users to run the same data directory on two active installations.
- Do not recommend deleting the data directory before a verified backup exists.
- Do not promise recovery of open trade state, payment accounts, or history when no current backup exists.
- Do not conflate Bisq 1 application data recovery with importing a Bisq 2 profile.

## Evidence / Sources

- `wiki:Data directory` documents where Bisq stores local application data.
- `wiki:Backing up application data` and `wiki:Restoring application data` cover full data-directory backup and restore.
- `wiki:Switching to a new data directory` and `wiki:Create a new wallet for your data directory` cover controlled migration and fresh-wallet workflows.
- `wiki:Restoring your wallet from seed`, `wiki:Last resort restore`, and `wiki:Emergency wallet` distinguish wallet-funds recovery from full application-state recovery.

## Review Notes

- Verify exact file names and directory paths against the current Bisq 1 docs before giving OS-specific step-by-step instructions.
- Treat open trades and disputes as high risk: preserve backups first and route uncertain cases to support/mediation rather than improvising file deletion.

## Last Change Summary

Added a consolidated page for recurring production candidates about Bisq 1 data-directory moves, seed restore limits, wallet recovery, and safe migration.

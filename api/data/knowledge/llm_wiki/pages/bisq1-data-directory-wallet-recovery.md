---
id: bisq1-data-directory-wallet-recovery
title: Bisq 1 data migration, backups and wallet recovery
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
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
- wiki:Command line options
- wiki:Changing your onion address
- wiki:Updating Bisq
- wiki:Reputation
- wiki:BSQ
- https://community.start9.com/t/restoring-history-from-account-on-laptop-to-bisq-on-start9/2138
- https://github.com/Start9-Community/bisq-startos/blob/4dcb82757d69aa7bf50d17ba9f3e3bfd2affb2c8/startos/manifest/index.ts
- https://bisq.wiki/Restoring_application_data
- https://github.com/bisq-network/bitcoinj/blob/6c32c0629d4ac7ecc95889eb1a46fa0d77a4e15a/core/src/main/java/org/bitcoinj/wallet/DeterministicUpgradeRequiredException.java#L19-L23
- https://github.com/bisq-network/bitcoinj/blob/6c32c0629d4ac7ecc95889eb1a46fa0d77a4e15a/core/src/main/java/org/bitcoinj/wallet/WalletProtobufSerializer.java#L706-L711
- https://github.com/bisq-network/bitcoinj/blob/6c32c0629d4ac7ecc95889eb1a46fa0d77a4e15a/core/src/main/java/org/bitcoinj/wallet/Wallet.java#L5223-L5249
- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/core/src/main/java/bisq/core/btc/setup/WalletConfig.java#L417-L431
- https://bisq.wiki/Resyncing_SPV_file
- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/core/src/main/java/bisq/core/dao/state/storage/DaoStateStorageService.java#L271-L290
- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/common/src/main/java/bisq/common/file/FileUtil.java#L312-L325
---
## Locate and preserve the actual data

Bisq 1 keeps wallet keys, trade contracts/history, payment accounts, dispute records, signing information, onion identity and local synchronization data in its data directory. It contains SPV chain state, not a Bitcoin Core full blockchain. Use the application's backup screen to open the directory or consult the official Data directory guide. Defaults include `~/Library/Application Support/Bisq` on macOS and `~/.local/share/Bisq` on Linux; custom launch options can change them. Finder's Go to Folder can open the macOS location. A missing visible default folder is not proof of lost funds.

Before restores, updates, identity changes or file operations, close Bisq and preserve a complete copy of the current directory and existing backups. Keep the original recovery evidence. An old backup contains only the application state present when it was taken; it cannot contain later trades. Restoring it can also replace newer SPV chain state and require synchronization again. Do not overwrite newer trade state merely to fix a balance display.

## Full migration and independent instances

For a move between computers or operating systems, close both applications and copy the complete current directory to the new installation's actual data location. Preserve the destination before replacing it and check directory depth: the expected `btc_mainnet` must not be nested inside an extra backup directory. Verify balances, payment accounts and active trade/dispute state after startup. Stop using the old live copy. Never alternate between old and migrated copies, even if they are not running simultaneously.

For a node appliance such as Start9, obtain the platform's actual data path and restore procedure; desktop paths and broad disk searches are not proof of the correct destination. If a migrated instance appears empty, first check the path, copied contents and startup logs.

A genuinely separate instance needs its own directory, wallet and onion identity. The documented `--appData` option chooses a different named directory, while `--appDataDir` specifies a directory path. This can provide an isolated test without deleting the original. Keep the original available to manage its existing obligations. Creating an independent instance does not itself destroy the original wallet, but an empty instance must not overwrite it.

To access the same installation from multiple computers, securely authenticated remote access to one controlled machine avoids divergent copies. Treat remote desktop access as access to the wallet; do not expose an unauthenticated desktop service.

A new empty wallet synchronizing quickly does not make an old wallet’s history synchronized. Restoring the old full directory also restores its local tracking state and may still require catch-up; do not overwrite the original to try to inherit the new wallet’s startup speed.

## Updates, missing records and seed limits

A normal compatible application update uses the existing data directory; it does not ordinarily require deleting offers, creating a wallet or transferring funds. Back up first, use official releases and follow any release-specific instructions, then verify active state after startup.

A seed can recover ordinary wallet BTC with the correct wallet type, derivation and creation information. It does not reconstruct the trade contracts, messages, payment accounts, signing identity, onion address or complete DAO/application state. It does not guarantee access to funds bound to active multisig trades. Prefer the newest intact full backup. If records vanished, inspect Funds > Transactions and the actual deposit before inferring lost funds, preserve the old disk/backups, and seek verified support for coordinated recovery.

If the displayed seed differs from the securely recorded original, stop replacing files. Preserve both states and confirm which data directory is in use. This discrepancy alone does not prove corruption or theft. Inspect public transaction evidence without sharing recovery secrets. External seed recovery is advanced; use documented compatible derivation and get support for open trades or BSQ. A normal BTC wallet can destroy BSQ coloring. For inspection alone, use watch-only tools.

## Payment-account export and identity

Payment-account export/import transfers account metadata, not a complete instance. Use the account's `EXPORT ACCOUNT` action and import via `Account > National Currency Accounts`; remove unwanted imported accounts only in the intended destination. `Export Account Age` and `Export Signed Witness` are instead proofs used for Bisq 2 reputation, not payment-account migration.

Restoring aging/signing separately requires the precise original account metadata, salt and matching signing key. Follow the official restore guide: replacing that key is not safe with active offers, trades or disputes, and Bisq must be closed with backups retained. Do not copy the whole UserPayload as an improvised shortcut. A local account nickname is not the account-holder identity.

A stable onion address links interactions with the same Bisq instance, not necessarily a real-world identity. Changing it can reduce linkability but makes an instance unreachable to existing trade/dispute peers. Do not rotate it during open trades or disputes. Use the official procedure and preserve identity backups; Tor-cache refresh is not onion-identity rotation. Do not apply Bisq 1 file procedures to Bisq 2 profiles.

## Replacing a wallet or directory

A local SPV resync is distinct from a fresh wallet or directory. For planned wallet replacement, first settle open offers, trades, mediations, arbitrations and pending BSQ/DAO actions and verify actual funds. The official new-wallet procedure can preserve other application state; a fresh directory changes more than the wallet. An old wallet's size alone does not justify abandoning active obligations.

When moving funds to a separate Bisq wallet, send BSQ through the BSQ wallet before moving the remaining BTC needed for its mining fee. Verify destination addresses and resulting BTC/BSQ balances; preserve the original until recovery is confirmed. No external ordinary Bitcoin wallet is a safe shortcut for BSQ.

If full restoration fails, preserve logs and diagnose the failure before selective recovery. Last resort restore is an exceptional documented procedure, not a synonym for SPV resync or permission to delete PendingTrades, DAO databases or arbitrary wallet files. Emergency tools require the same caution. Bisq 2 does not import a Bisq 1 wallet or its open trades; its reputation-proof imports are separate.

## Historical StartOS migration path

A December 2024 Start9 support reply named /embassy-data/package-data/volumes/bisq/data/bisq/btc_mainnet for its then-current Bisq package, required stopping the service before copying, and explicitly limited support for manual migration. That path is historical: current package layouts can differ. Confirm the installed package’s volume mapping and ownership, preserve both source and destination backups and stop both instances before a reviewed full-data transfer. Do not use payment-account import or copy only a signing key and UserPayload to stand in for a complete instance; StartOS-native backups have their own restore workflow.

## Wallet loading errors: preserve the failing state

DeterministicUpgradeRequiredException concerns an older non-HD wallet being used with HD functionality before the required upgrade. Preserve the original wallet and key material; a modern seed must not be assumed to cover every old random key. Record the application version and loading stack trace for version-specific recovery. This exception is not a DAO or Tor diagnosis.

UnreadableWalletException with Wallet contained duplicate transaction is raised while deserializing duplicate wallet transactions. In the inspected implementation, loading must succeed before replay can reset transaction state, so deleting the SPV chain does not bypass this loading failure. Preserve the directory and rolling backups; deleting an unrelated BSQ tracking store is not a repair.

Expected PENDING or IN_CONFLICT, was BUILDING means a transaction in bitcoinj’s pending collection has a conflicting confirmed confidence state. It does not establish DAO corruption. If wallet backups have already been swapped, stop mixing files and preserve every source backup and the change history. Identify the affected wallet and a coherent recoverable state with verified support before replacement; arbitrarily recent BTC and BSQ backups are not automatically a safe pair. Preserve active trade identity and contracts.

## Archived DAO recovery data

In the inspected Bisq 1 implementation, btc_mainnet/db/out_of_sync_dao_data is a destination for timestamped copies of DAO files moved aside during recovery. It is not the active DAO store. Once recovery is complete and those diagnostic copies are no longer needed, close Bisq, archive that exact directory outside the live directory and verify the archive before removing only those old local copies. Keep them while support investigates. Do not extend this cleanup to live DaoStateStore, SignedWitnessStore, wallets or trade databases; the removed historical copies are not reconstructed on startup.

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 545, 798, 851, 1138, 1374, 1539, 1735, 2157. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Evidence / Sources

- [Data directory](https://bisq.wiki/Data_directory): official procedure or scope referenced above.
- [Backing up application data](https://bisq.wiki/Backing_up_application_data): official procedure or scope referenced above.
- [Restoring application data](https://bisq.wiki/Restoring_application_data): official procedure or scope referenced above.
- [Switching to a new data directory](https://bisq.wiki/Switching_to_a_new_data_directory): official procedure or scope referenced above.
- [Create a new wallet for your data directory](https://bisq.wiki/Create_a_new_wallet_for_your_data_directory): official procedure or scope referenced above.
- [Restoring your wallet from seed](https://bisq.wiki/Restoring_your_wallet_from_seed): official procedure or scope referenced above.
- [Last resort restore](https://bisq.wiki/Last_resort_restore): official procedure or scope referenced above.
- [Emergency wallet](https://bisq.wiki/Emergency_wallet): official procedure or scope referenced above.
- [Command line options](https://bisq.wiki/Command_line_options): official procedure or scope referenced above.
- [Changing your onion address](https://bisq.wiki/Changing_your_onion_address): official procedure or scope referenced above.
- [Updating Bisq](https://bisq.wiki/Updating_Bisq): official procedure or scope referenced above.
- [Reputation](https://bisq.wiki/Reputation): official procedure or scope referenced above.
- [BSQ](https://bisq.wiki/BSQ): official procedure or scope referenced above.

- https://community.start9.com/t/restoring-history-from-account-on-laptop-to-bisq-on-start9/2138
- https://github.com/Start9-Community/bisq-startos/blob/4dcb82757d69aa7bf50d17ba9f3e3bfd2affb2c8/startos/manifest/index.ts
- https://bisq.wiki/Bisq_2_Wallet
- https://github.com/bisq-network/bitcoinj/blob/6c32c0629d4ac7ecc95889eb1a46fa0d77a4e15a/core/src/main/java/org/bitcoinj/wallet/DeterministicUpgradeRequiredException.java#L19-L23
- https://github.com/bisq-network/bitcoinj/blob/6c32c0629d4ac7ecc95889eb1a46fa0d77a4e15a/core/src/main/java/org/bitcoinj/wallet/WalletProtobufSerializer.java#L706-L711
- https://github.com/bisq-network/bitcoinj/blob/6c32c0629d4ac7ecc95889eb1a46fa0d77a4e15a/core/src/main/java/org/bitcoinj/wallet/Wallet.java#L5223-L5249
- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/core/src/main/java/bisq/core/btc/setup/WalletConfig.java#L417-L431
- https://bisq.wiki/Resyncing_SPV_file
- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/core/src/main/java/bisq/core/dao/state/storage/DaoStateStorageService.java#L271-L290
- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/common/src/main/java/bisq/common/file/FileUtil.java#L312-L325

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

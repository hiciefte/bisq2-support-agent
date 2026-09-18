---
id: bisq1-wallet-spv-balance
title: Bisq 1 wallet balances and SPV recovery
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: high
source_refs:
- wiki:Wallet
- wiki:Watch keys
- wiki:Import Bisq wallet as watch only wallet in Sparrow
- wiki:Resyncing SPV file
- wiki:Troubleshooting wallet issues
- wiki:Create a new wallet for your data directory
- wiki:Emergency wallet
- wiki:BSQ
- wiki:Creating a payment account
- wiki:Trading Monero
- wiki:Reducing memory usage
- wiki:Performance Tips
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/gradle/libs.versions.toml
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/util/validation/BtcAddressValidator.java
- https://github.com/bisq-network/bitcoinj/blob/6c32c0629d4ac7ecc95889eb1a46fa0d77a4e15a/core/src/main/java/org/bitcoinj/core/SegwitAddress.java
- https://github.com/bisq-network/bitcoinj/blob/6c32c0629d4ac7ecc95889eb1a46fa0d77a4e15a/core/src/main/java/org/bitcoinj/core/Bech32.java
- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/common/src/main/java/bisq/common/config/Config.java#L364-L369
- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/core/src/main/java/bisq/core/app/misc/ExecutableForAppWithP2p.java#L273-L310
- https://docs.oracle.com/en/java/javase/21/docs/specs/man/java.html
- https://bisq.wiki/Wallet
- https://bisq.wiki/Resyncing_SPV_file
- https://github.com/bisq-network/bitcoinj/blob/6c32c0629d4ac7ecc95889eb1a46fa0d77a4e15a/core/src/main/java/org/bitcoinj/wallet/Wallet.java#L5223-L5249
- https://bisq.wiki/Command_line_options
- https://bisq.wiki/Security_deposit
- https://bisq.wiki/Support_Agent_Knowledge_Base
---
## Scope

Bisq 1 wallet diagnosis and local SPV recovery. An ordinary withdrawal, a trade fee, a deposit and a payout are different transactions. This page does not authorize deleting trade state or changing a trade's settlement.

## Verify balances and transactions

Compare `Funds > Transactions` and the outputs under `Funds > Send Funds` with actual on-chain transactions. Distinguish available, reserved and locked amounts; a displayed total or a change after resync does not prove loss. Identify the correct transaction ID and receiving address. A trade ID is not a blockchain transaction ID. An independent explorer or a documented watch-only wallet can help even while Bisq is synchronizing.

A pending transaction exists but has not confirmed. A transaction absent from one explorer needs investigation; absence alone does not prove it was never broadcast. A confirmed transaction missing from Bisq, or a locally spendable output already spent on chain, suggests stale wallet tracking. If a withdrawal did not appear, inspect its inputs and original status before retrying, to avoid duplicate payment. Do not apply the failed-trade workflow to an ordinary withdrawal.

For persistent discrepancies after completed recovery, provide verified support with the relevant transaction status, available/reserved/locked totals, Send Funds outputs, exact error, version and steps already attempted. Redact unrelated financial details. Do not send seeds or private keys.

Compare actual currently unspent outputs, not an explorer’s lifetime received total with Bisq’s available balance. During an incomplete resync, a displayed Failed trade label is not proof of the trade outcome and is not guaranteed to correct itself. Recheck the actual deposit after synchronization; a confirmed deposit may still lock funds. Do not move or delete trade records merely to clear that display.

## Documented SPV procedure

Back up the complete data directory. For a wallet-chain inconsistency, use `Settings > Network Info > RESYNC SPV WALLET` and complete the prompted restarts, including the final restart. The bitcoinj confidence-state error `Expected PENDING or IN_CONFLICT, was BUILDING` concerns wallet state; it does not by itself prove DAO corruption or establish which recovery will work. Preserve the exact error and prior changes and seek version-appropriate diagnostic support, especially with an active trade, instead of inventing file deletions.

If the interface cannot be reached, the official guide describes a closed-application fallback using `btc_mainnet/wallet/bisq.spvchain`, followed by the required restarts. Follow that exact guide after preserving a backup; it is not permission to remove wallet, trade or DAO files.

Resync updates local blockchain tracking. It does not raise mining fees, accelerate confirmation, clear the network mempool, create a missing deposit, refund fees, or unilaterally release multisig escrow. A documented resync may be appropriate during an open trade to recognize confirmed transactions; replacing the wallet or data directory is a different operation.

The Expected PENDING or IN_CONFLICT, was BUILDING exception specifically reflects inconsistent bitcoinj pending-transaction/confidence bookkeeping. For previous backup-file swaps or persistent startup failure, see the wallet-loading-error section of bisq1-data-directory-wallet-recovery; preserve the existing trade identity.

## Interrupted resync and performance

A normal restart can help a stalled process, but observe whether progress resumes. If restarting an interrupted resync repeatedly resets progress to zero, the official troubleshooting section describes removing the root-directory `resyncSpv` marker with Bisq closed. This marker differs from `bisq.spvchain`: removing the marker is intended to retain progress, not trigger a fresh chain rebuild. If the marker is absent, do not substitute another file. Balances may remain inaccurate until background synchronization finishes.

Check advancing blocks, progress and logs rather than relying on a peer count alone. Working Bitcoin peers are necessary; connected Bisq P2P peers do not prove that connection. Time varies with wallet age, transaction count, hardware, workload and connectivity. Give the process time and resources; there is no guaranteed fifteen-minute duration or universal 700-transaction replacement threshold. A personal node may improve retrieval but is not mandatory and does not eliminate the SPV wallet.

Distinguish a slow resync from the process exiting. For an exit, retain the last bisq.log entries and operating-system crash report, including any complete OutOfMemoryError. Bisq’s maxMemory option is a headless-service monitoring threshold in the inspected code, not a desktop JVM heap allocation setting. Java -Xmx sets the maximum heap; -XX:MaxRAM participates in ergonomic heap sizing. Check the effective launcher configuration and leave memory for the operating system. Changing a ceiling or removing a resync marker does not diagnose the original crash.

Repeated failed resyncs warrant diagnosis before another reset. A fresh wallet is a planned maintenance option only after all offers, trades, disputes and pending BSQ/DAO actions are settled and funds verified; use the recovery page and official procedure.

Bitcoin Core’s bitcoin.conf configures Core, not Bisq. Use documented Bisq options for an actual application configuration change rather than deleting extra state merely to reach the interface.

## Inspection, emergency tools and other assets

An xpub permits compatible watch-only inspection, not spending or restoring trades. It can reveal wallet history, so do not publish it. Use the documented Sparrow setup and correct derivation information; do not assume arbitrary mobile-wallet compatibility.

The emergency wallet opens with `Ctrl+E` (`Cmd+E` on macOS). Opening it does not establish that all displayed funds are freely spendable. Emergency withdrawal or external seed recovery is a last resort after backup and verified support review, especially with active obligations or BSQ.

Check BSQ under `DAO > BSQ Wallet`, separately from ordinary BTC. Bisq's normal BTC send flow distinguishes BSQ outputs; ordinary external Bitcoin wallets do not preserve BSQ coloring. Retain BTC for ordinary BSQ-transfer mining fees. To receive or send BSQ, use the BSQ-aware Bisq flow, not an external BTC wallet or an assumed universal minimum residual balance. A confirmed-looking BTC transaction is not sufficient evidence of valid spendable BSQ; check DAO consensus too.

For supported altcoins, configure the external wallet address in `Account > Altcoin Accounts` and check the coin-specific proof requirements. Bisq 1 has no internal XMR wallet: verify incoming Monero in the synchronized external Monero wallet before confirming receipt. Do not invent an internal altcoin withdrawal screen.

## Taproot withdrawal destinations

The reviewed Bisq 1.10.8 release pins a bitcoinj address parser that does not support Taproot withdrawal destinations. Mainnet Taproot normally begins bc1p; native SegWit version 0 normally begins bc1q. “Any bc1 address” is therefore not a valid correction. Request a valid compatible Bitcoin mainnet receiving address from a wallet you control, if that wallet supports it, and verify the address rather than editing its prefix. AddressFormatException can also mean malformed input, checksum failure or the wrong network. Recheck this release-specific support boundary in later versions.

## Completed trade but missing balance

For each trade, identify the payout transaction and the output to your wallet, including its confirmation state. A confirmed deposit alone does not prove you received the payout. Compare that output with wallet transaction history and any subsequent spending or reservations. If the payout is confirmed but locally missing, investigate wallet synchronization; if no payout exists or its destination is unclear, preserve the trade and ask support to investigate completion. Do not rebuild DAO state or send a replacement payment solely from a missing balance.

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 538, 722, 769, 876, 1128, 1288, 1362, 1513, 1816, 2373, 2427. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Evidence / Sources

- [Wallet](https://bisq.wiki/Wallet): official procedure or scope referenced above.
- [Watch keys](https://bisq.wiki/Watch_keys): official procedure or scope referenced above.
- [Import Bisq wallet as watch only wallet in Sparrow](https://bisq.wiki/Import_Bisq_wallet_as_watch_only_wallet_in_Sparrow): official procedure or scope referenced above.
- [Resyncing SPV file](https://bisq.wiki/Resyncing_SPV_file): official procedure or scope referenced above.
- [Troubleshooting wallet issues](https://bisq.wiki/Troubleshooting_wallet_issues): official procedure or scope referenced above.
- [Create a new wallet for your data directory](https://bisq.wiki/Create_a_new_wallet_for_your_data_directory): official procedure or scope referenced above.
- [Emergency wallet](https://bisq.wiki/Emergency_wallet): official procedure or scope referenced above.
- [BSQ](https://bisq.wiki/BSQ): official procedure or scope referenced above.
- [Creating a payment account](https://bisq.wiki/Creating_a_payment_account): official procedure or scope referenced above.
- [Trading Monero](https://bisq.wiki/Trading_Monero): official procedure or scope referenced above.
- [Reducing memory usage](https://bisq.wiki/Reducing_memory_usage): official procedure or scope referenced above.
- [Performance Tips](https://bisq.wiki/Performance_Tips): official procedure or scope referenced above.

- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/gradle/libs.versions.toml
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/util/validation/BtcAddressValidator.java
- https://github.com/bisq-network/bitcoinj/blob/6c32c0629d4ac7ecc95889eb1a46fa0d77a4e15a/core/src/main/java/org/bitcoinj/core/SegwitAddress.java
- https://github.com/bisq-network/bitcoinj/blob/6c32c0629d4ac7ecc95889eb1a46fa0d77a4e15a/core/src/main/java/org/bitcoinj/core/Bech32.java
- https://bisq.wiki/Resyncing_SPV_file#Fix_an_Incomplete_SPV_Resync
- https://bisq.wiki/Connecting_to_your_own_Bitcoin_node#Troubleshooting
- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/common/src/main/java/bisq/common/config/Config.java#L364-L369
- https://github.com/bisq-network/bisq/blob/e8ad421428bd1557d3a0484f704f9d5515ae6b2e/core/src/main/java/bisq/core/app/misc/ExecutableForAppWithP2p.java#L273-L310
- https://docs.oracle.com/en/java/javase/21/docs/specs/man/java.html
- https://github.com/bisq-network/bitcoinj/blob/6c32c0629d4ac7ecc95889eb1a46fa0d77a4e15a/core/src/main/java/org/bitcoinj/wallet/Wallet.java#L5223-L5249
- https://bisq.wiki/Command_line_options
- https://bisq.wiki/Security_deposit
- https://bisq.wiki/Support_Agent_Knowledge_Base

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

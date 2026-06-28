---
id: bisq1-wallet-spv-balance
title: Bisq 1 wallet balance, SPV resync, BSQ, and external asset accounts
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: suddenwhipvapor
reviewed_at: '2026-06-27'
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
- wiki:Trading Monero
- faq:1119
- faq:1134
- faq:1139
- faq:1149
- faq:1162
- faq:1166
---
## Canonical Support Answer

For Bisq 1 wallet balance problems, separate wallet-chain display state from actual on-chain funds. If Bisq shows a balance that does not match the blockchain, if confirmed transactions are missing, or if UTXOs shown under `Funds > Send funds` no longer exist on a block explorer, the normal first recovery step is an SPV resync from `Settings > Network Info > Resync SPV Wallet`.

SPV resync rebuilds local blockchain data used by Bisq's Bitcoin wallet. It can take minutes or hours depending on wallet age, transaction count, hardware, and network conditions. Back up the data directory first, let the resync complete, and do not treat a slow resync as proof that funds are lost. For old wallets with hundreds of transactions or repeated SPV-resync needed, consider the documented new-wallet workflow only after all open trades, offers, mediations, arbitrations, BSQ actions, and DAO actions are settled.

If the user needs to independently inspect wallet state, compare Bisq's UTXOs with a block explorer or a watch-only wallet. Do not ask for seed words or private keys in chat. If normal wallet recovery fails and Bisq cannot spend funds, use wallet backup restore or emergency-wallet guidance only as a last resort and preferably with support review.

BSQ is not the same as plain BTC. BSQ balances belong in the DAO/BSQ wallet flow and require DAO sync to be recognized and spent. When moving BTC away from an old Bisq wallet, keep enough BTC for any needed BSQ transaction fees if the user still needs to move BSQ. Moving BSQ outside Bisq's UI is advanced and not officially supported as a routine path.

Bisq 1 does not include an XMR wallet. For Monero trades, the user configures an external Monero wallet address in the altcoin account settings and verifies incoming XMR in that external Monero wallet. Do not tell users to look for an internal Bisq XMR wallet.

## Applies When

- The user asks how to perform an SPV resync.
- Bisq shows zero or incorrect BTC balance despite on-chain funds.
- Bisq does not show a confirmed wallet transaction.
- The user wants to verify wallet state with UTXOs, block explorers, or a watch-only wallet.
- The user asks whether to create a new wallet while active trades exist.
- The user asks where to send or view BSQ in Bisq 1.
- The user asks whether `Funds` BTC UTXOs include BSQ.
- The user asks where the XMR wallet/address is in Bisq.

## Do Not Say

- Do not say wallet funds are lost before checking on-chain state.
- Do not tell users to create a new wallet while open trades, offers, mediations, arbitrations, or pending BSQ/DAO actions exist.
- Do not ask users to share seed words, private keys, or wallet files in public support.
- Do not present emergency-wallet use as normal first-line troubleshooting.
- Do not conflate BTC wallet balance, BSQ wallet balance, and external altcoin wallet balances.
- Do not quote a fixed SPV resync duration as a guarantee.

## Evidence / Sources

- `wiki:Wallet`, `wiki:Watch keys`, and `wiki:Import Bisq wallet as watch only wallet in Sparrow` document wallet-state inspection options.
- `wiki:Resyncing SPV file` and `wiki:Troubleshooting wallet issues` document SPV resync, wallet backup restore, and new-wallet fallback.
- `wiki:Create a new wallet for your data directory` explains when a new wallet can reduce old-wallet resync problems.
- `wiki:Emergency wallet` documents last-resort fund recovery.
- `wiki:BSQ` documents BSQ as colored bitcoin recognized by Bisq software.
- `wiki:Trading Monero` documents external Monero wallet proof/address requirements.
- `faq:1119`, `faq:1139`, and `faq:1149` cover wallet status and SPV resync support answers.
- `faq:1134`, `faq:1162`, and `faq:1166` cover BSQ/DAO wallet edge cases.

## Review Notes

- Exact UI labels vary by Bisq 1 version; verify before giving click-by-click instructions.
- Keep XMR/altcoin advice limited to external-wallet setup and proof; do not turn this page into a full altcoin trading guide.

## Last Change Summary

Added a consolidated Bisq 1 wallet page to absorb recurring SPV, wallet-balance, BSQ, and external-altcoin-account candidates without bloating the data-directory recovery page.

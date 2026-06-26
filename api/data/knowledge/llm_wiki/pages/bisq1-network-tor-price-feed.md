---
id: bisq1-network-tor-price-feed
title: Bisq 1 network, Tor, Bitcoin peers, and price-feed troubleshooting
type: llm_wiki
page_type: support_playbook
status: proposed
protocol: multisig_v1
reviewed_by: null
reviewed_at: null
risk_level: medium
source_refs:
  - wiki:Troubleshooting network issues
  - wiki:Network status indicator
  - wiki:Connecting to your own Bitcoin node
  - wiki:Installing your own Bitcoin node
  - wiki:Command line options
  - wiki:Resyncing SPV file
  - faq:1139
---
## Canonical Support Answer

For Bisq 1 connection, Tor, Bitcoin-peer, offerbook, or price-feed issues, separate network reachability from wallet-chain state. First verify basic local causes: the operating-system clock is synchronized, the user is on the latest supported Bisq version, the network status indicator has peer connections, and Tor/Bitcoin connectivity is not blocked by the OS, firewall, VPN, antivirus, router, or local network.

If Bisq is online but price-node, offerbook, or peer errors persist, refresh Tor files from the documented network/Tor settings and restart. Keep the Tor hidden-service identity file when the source says to preserve it. If the issue is weak connectivity, try a different network or hotspot to distinguish local network blocking from Bisq/Tor issues.

If the Bitcoin network connection is the problem, try the documented provided Bitcoin nodes or a trusted personal Bitcoin node configuration. For a local Bitcoin Core node, Bisq needs a reachable unpruned node with settings such as `server=1`, `prune=0`, and `peerbloomfilters=1`; if the node is on another machine, confirm the address, firewall, and listen settings. Start9/Ronin/custom-node reports may require platform-specific support rather than generic Bisq instructions.

Temporary seed-node bans, custom seed nodes, or command-line network overrides should be given only when source-backed and incident-specific. Tell users to remove temporary bans or overrides after the incident is resolved so they do not accumulate stale configuration.

If the symptom is a trade or wallet transaction not advancing after network recovery, do not keep changing network settings blindly. Verify the relevant transaction state. Use SPV resync only for wallet-chain display or transaction-recognition problems, not for generic Tor, price-feed, or offerbook failures.

## Applies When

- Bisq 1 shows few or no Bitcoin/P2P connections.
- Bisq 1 stalls during initial network data, Tor bootstrap, or seed-node download.
- The user sees price-node, price-feed, Tor, peer-connection, or offerbook errors.
- The user asks whether to use a provided Bitcoin node, custom Bitcoin node, or command-line node option.
- The user needs to refresh Tor files or recover from stale network state.
- The user is troubleshooting a local Bitcoin node, Start9/Ronin node, firewall, VPN, or antivirus interaction.
- A connection issue is being confused with a stuck wallet/trade issue.

## Do Not Say

- Do not tell users to delete the data directory as a first network-troubleshooting step.
- Do not present temporary seed-node bans or custom node overrides as permanent configuration.
- Do not use SPV resync for generic Tor or price-feed failures unless wallet-chain state is also wrong.
- Do not assume a network error means funds are lost.
- Do not recommend arbitrary third-party Bitcoin nodes without source-backed context.
- Do not treat platform-specific Start9/Ronin/macOS firewall issues as universal Bisq behavior.

## Evidence / Sources

- `wiki:Troubleshooting network issues` documents connection troubleshooting and Tor reset paths.
- `wiki:Network status indicator` explains how to interpret network connection state.
- `wiki:Connecting to your own Bitcoin node` and `wiki:Installing your own Bitcoin node` document Bitcoin-node configuration boundaries.
- `wiki:Command line options` covers command-line network overrides.
- `wiki:Resyncing SPV file` and `faq:1139` apply when wallet-chain state is stale after connectivity is restored.

## Review Notes

- Recheck current Bisq 1 version and any active seed-node incident before giving exact onion addresses or command-line workarounds.
- Keep price-feed guidance conservative: connection workarounds should not become market-price advice.
- Production candidates about confirmed deposits, old wallets, SPV memory pressure, and stuck trades were intentionally routed to wallet/deposit pages rather than this network page.

## Last Change Summary

Curated network candidates into one page covering Tor refresh, peer/price-feed/offerbook failures, local Bitcoin node requirements, temporary overrides, and the boundary between network troubleshooting and SPV wallet recovery.

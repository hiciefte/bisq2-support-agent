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
---
## Canonical Support Answer

For Bisq 1 connection, Tor, Bitcoin-peer, or price-feed issues, separate network reachability from wallet-chain state. First verify basic local causes: system clock is synchronized, the user is on the latest supported Bisq 1 version, the network status indicator has peer connections, and Tor/Bitcoin connectivity is not blocked by the OS, firewall, VPN, or local network.

If Bisq is online but price-node or peer errors persist, refresh Tor files from the Bisq network settings and restart. If the Bitcoin network connection is the problem, try the documented provided Bitcoin nodes or a trusted personal Bitcoin node configuration. For temporary seed-node or custom-node workarounds, give the exact documented command-line option only when the source supports it, and tell the user to remove temporary node bans or overrides after the incident is resolved.

If the symptom is a trade or wallet transaction not advancing after network recovery, do not keep changing network settings blindly. Verify the relevant transaction state and use SPV resync only for wallet-chain display or transaction-recognition problems.

## Applies When

- Bisq 1 shows few or no Bitcoin/P2P connections.
- The user sees price-node, price-feed, Tor, or peer-connection errors.
- The user asks whether to use a provided Bitcoin node, custom Bitcoin node, or command-line node option.
- The user needs to refresh Tor files or recover from stale network state.
- A connection issue is being confused with a stuck wallet/trade issue.

## Do Not Say

- Do not tell users to delete the data directory as a first network-troubleshooting step.
- Do not present temporary seed-node bans or custom node overrides as permanent configuration.
- Do not use SPV resync for generic Tor or price-feed failures unless wallet-chain state is also wrong.
- Do not assume a network error means funds are lost.
- Do not recommend arbitrary third-party Bitcoin nodes without source-backed context.

## Evidence / Sources

- `wiki:Troubleshooting network issues` documents connection troubleshooting and Tor reset paths.
- `wiki:Network status indicator` explains how to interpret network connection state.
- `wiki:Connecting to your own Bitcoin node` and `wiki:Installing your own Bitcoin node` document Bitcoin-node configuration boundaries.
- `wiki:Command line options` covers command-line network overrides.
- `wiki:Resyncing SPV file` applies when wallet-chain state is stale after connectivity is restored.

## Review Notes

- Recheck current Bisq 1 version and any active seed-node incident before giving exact onion addresses or command-line workarounds.
- Keep price-feed guidance conservative: connection workarounds should not become market-price advice.

## Last Change Summary

Added a consolidated page for recurring production candidates about Bisq 1 network status, Tor refresh, Bitcoin peers, custom nodes, and price-feed errors.

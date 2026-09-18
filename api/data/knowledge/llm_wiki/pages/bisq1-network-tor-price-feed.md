---
id: bisq1-network-tor-price-feed
title: Bisq 1 Tor, Bitcoin peers, messages and price-feed troubleshooting
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: medium
source_refs:
- wiki:Troubleshooting network issues
- wiki:Network status indicator
- wiki:Connecting to your own Bitcoin node
- wiki:Command line options
- wiki:Resyncing SPV file
- wiki:Performance Tips
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/api/model/OfferInfo.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/offer/Offer.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/offer/availability/tasks/ProcessOfferAvailabilityResponse.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/trade/protocol/TradeProtocol.java
- https://bisq.wiki/Troubleshooting_network_issues
- https://github.com/dutu/run-on-tails/commit/2165cc6ccb0ab3feecd161e9c9c50558048766fe
- https://bisq.wiki/Running_Bisq_on_Tails
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/common/src/main/java/bisq/common/config/Config.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/user/Preferences.java
- https://bisq.wiki/Connecting_to_your_own_Bitcoin_node#Troubleshooting
- https://bisq.wiki/Command_line_options
- https://bisq.wiki/Connecting_to_your_own_Bitcoin_node
---
## Identify the failing connection

Bisq 1 P2P peers, Bitcoin peers and price-feed services are different. A green P2P indicator or working Tor Browser does not establish a working Bitcoin connection. Zero usable Bitcoin peers prevents SPV progress even if Bisq P2P peers are connected. Conversely, resyncing a wallet does not repair price-feed access or trade-message delivery.

Check the exact error, supported application version, automatically synchronized system clock and peer/connection mode in Network Info. Record any operating-system privacy or firewall warning after an OS update; do not turn a diagnostic check into disabling platform protection. Tor Browser on the same connection or another network can help isolate a connectivity issue. If testing a VPN change, consider its privacy implications and do not broadly disable security software.

For repeated price-node errors, failure to receive a filter object from seed nodes, or stalled Bitcoin-over-Tor connections, use the documented network diagnosis. When Tor state appears stale, open `Settings > Network Info > Open Tor Settings`, choose the built-in outdated-Tor-files cleanup/shutdown action, then restart and allow connections to establish. This is different from clearing Tor Browser files or deleting the hidden-service identity. Preserve the data directory and identity; no fixed number of retries is guaranteed to work.

## Own-node configuration

Bisq needs a compatible Bitcoin P2P service. Sparrow connecting successfully through Electrum or RPC does not prove that Bisq can reach that service. Follow the official own-node guide for a fully synchronized node providing historical blocks and bloom-filter support. The guide documents `prune=0` and `peerbloomfilters=1`; it also lists `server=1`, but that setting alone is not proof of a reachable P2P listener.

Distinguish a same-machine localhost connection from a node elsewhere on the LAN or a Tor onion endpoint. Match the address, transport, listening interface and narrowly scoped firewall access. A local connection need not expose the node publicly. A configured own-node setup can intentionally show one Bitcoin peer; peer count alone does not establish failure. Appliance-specific issues may need that platform's support. If a bad custom-node setting blocks startup, use the current official troubleshooting procedure to return to provided nodes rather than a remembered third-party onion address.

A personal node may improve chain-data retrieval, but Bisq still uses its SPV wallet. It does not accelerate mining confirmations, guarantee instant recovery or make every action faster. A separate node may synchronize independently; do not switch Bisq to an unsynchronized node or trade while Bisq wallet state is unreliable during a resync.

A resync correcting a display does not by itself establish whether a connection fault or wallet defect caused the original discrepancy. Turning off Bitcoin-over-Tor is a deliberate transport/privacy choice that can expose connection information to the selected Bitcoin node; it is not a universal fix for stalled synchronization.

## Messages, stalled trades and evidence

For a blocked Payment started notification, inspect Bisq P2P connectivity. A message-delivery failure is not evidence the bank transfer failed: do not send fiat again. Keep payment proof and contact the peer or mediator through the existing trade if delivery remains blocked. If payout is waiting for Bitcoin peers, inspect the configured mode and preserve the trade; do not delete its state.

After repeated failed recovery, collect relevant Bisq logs (available through the backup/log-export interface), exact error, version, node settings, peer counts and steps already attempted. Share only necessary information through verified support. An SPV resync is appropriate for stale wallet-chain state after connectivity is restored, not as a generic network reset.

Temporary seed-node bans or command-line overrides need current incident evidence and removal afterward. A historical release number or infrastructure address is not a current fix. If the market reference price itself looks wrong, check the actual BTC/fiat amounts before committing and use the separate payment/price-checks page.

## API availability and trade-protocol timeouts

In the reviewed Bisq 1 gRPC implementation, OfferInfo.state reflects the local Offer availability state, initialized to UNKNOWN. A listing is not an availability handshake with its maker. UNKNOWN is neither a trade-state flag nor proof of a sync fault or guaranteed tradability. Handle the actual availability/take-offer response.

The error “Protocol did not complete in 120 sec” records an incomplete trade-protocol step, not a unique cause such as an unavailable offer. If recreating offers and resyncing already failed, inspect the preceding log error, trade state and Bisq P2P connectivity. Preserve the state and check any fee/deposit publication before retrying; SPV resync does not repair trade-message delivery.

## Tails integration and Bitcoin-only transport overrides

The official Bisq 1 Tails recipe uses the external Tor control interface with --torControlPort 951, --torControlCookieFile=/var/run/tor/control.authcookie and --torControlUseSafeCookieAuth, plus an onion-grater policy and persistent data. A verified May 2024 policy change added GETINFO status/bootstrap-phase handling; the recipe also permits net/listeners/socks. Check these specific integration requirements when diagnosing the historical 1.9.15 startup problem. They are not proof that every Tails failure has the same cause or permission to run an unreviewed moving script.

Bisq 1 also accepts --useTorForBtc=false at launch, so its BitcoinJ routing can be changed before reaching the UI. This does not remove Tor from the Bisq P2P network. Direct connections to remote Bitcoin peers expose different network information; use a correctly configured trusted local node where appropriate and restore the intended routing after a deliberate test. Do not add speculative SPV or identity-file deletion to this transport setting.

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 395, 607, 1010, 1269, 1322, 1325, 1337, 1361, 1443. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Evidence / Sources

- [Troubleshooting network issues](https://bisq.wiki/Troubleshooting_network_issues): official procedure or scope referenced above.
- [Network status indicator](https://bisq.wiki/Network_status_indicator): official procedure or scope referenced above.
- [Connecting to your own Bitcoin node](https://bisq.wiki/Connecting_to_your_own_Bitcoin_node): official procedure or scope referenced above.
- [Command line options](https://bisq.wiki/Command_line_options): official procedure or scope referenced above.
- [Resyncing SPV file](https://bisq.wiki/Resyncing_SPV_file): official procedure or scope referenced above.
- [Performance Tips](https://bisq.wiki/Performance_Tips): official procedure or scope referenced above.

- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/api/model/OfferInfo.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/offer/Offer.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/offer/availability/tasks/ProcessOfferAvailabilityResponse.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/trade/protocol/TradeProtocol.java
- https://github.com/dutu/run-on-tails/commit/2165cc6ccb0ab3feecd161e9c9c50558048766fe
- https://bisq.wiki/Running_Bisq_on_Tails
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/common/src/main/java/bisq/common/config/Config.java
- https://github.com/bisq-network/bisq/blob/1b5f317641e04368cd56d2c09af4860fac970136/core/src/main/java/bisq/core/user/Preferences.java
- https://bisq.wiki/Connecting_to_your_own_Bitcoin_node#Troubleshooting

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

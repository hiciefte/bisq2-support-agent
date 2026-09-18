---
id: bisq2-startup-network-notifications
title: Bisq 2 startup, network, messaging and notifications
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: bisq_easy
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: medium
source_refs:
- https://bisq.wiki/Bisq_2
- https://bisq.wiki/Downloading_and_installing
- https://bisq.wiki/Dispute_Resolution_in_Bisq_2
- https://github.com/bisq-network/bisq2/issues
- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/network/tor/tor-common/src/main/java/bisq/network/tor/common/torrc/ClientTorrcGenerator.java
- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/network/tor/tor-common/src/main/java/bisq/network/tor/common/torrc/Torrc.java
- https://github.com/bisq-network/bisq2/issues/2826#issuecomment-2353496480
- https://github.com/bisq-network/bisq2/issues/2587#issuecomment-2276260039
- https://bisq.wiki/Bisq_2#Installation
---
## Canonical Support Answer

First identify the Bisq 2 version, operating system and exact symptom: an application crash is different from a process still waiting for initial network data. Record the error and try one normal restart. Check a supported release, operating-system time synchronization and Tor/network reachability. A working Tor Browser is useful diagnostic evidence, but does not prove that Bisq's own Tor connection works. A working Bisq 1 installation likewise does not prove Bisq 2 connectivity.

For missing offers or a network-data stall, inspect the client's connection status and whether it makes progress. Do not prescribe a fixed peer-count threshold or guess the meaning of a version-specific status label. Bisq Easy does not use the Bisq 1 internal wallet/SPV-resync workflow.

For a local Tor control-port error, retain the exact startup message and note whether it recurs after restart. That error alone does not justify changing router ports, adding an arbitrary proxy, rotating an onion identity or restoring a profile. If one profile can send messages and another cannot, report the affected profile, chat type and error; preserve both profiles rather than creating more test identities or overwriting the failing one.

For delayed notifications, missing sound or failed mobile pairing, provide the desktop/mobile versions, operating system and relevant redacted logs through established support or the Bisq 2 issue tracker. Do not claim a historical release fixed every notification issue, or infer Bluetooth or macOS quarantine trouble from a running application's notification problem.

Before clearing a ghost notification, check the correct profile, open trades and actual payment state. Clearing notifications is appropriate only for a stale badge with no unresolved trade. If payment or BTC delivery is unresolved, use the trade chat and mediation. For a fully settled trade whose UI remains stuck, ask support which cleanup action fits the installed version; do not cancel merely to hide the symptom.

If requesting mediation fails or the control is unavailable, keep the trade evidence and contact established support for mediator assistance. Repeated failed clicks, file deletion and Bisq 1 keyboard instructions are not fixes for an unidentified Bisq 2 error.

## Recovery boundaries

Preserve a complete data-directory copy before repairs. A protobuf, database or Tor-file workaround must match the exact current issue and client version. Installer and signature problems belong to `bisq-installation-update-signatures`; do not reuse terminal commands for another application bundle or release.

## Embedded Tor ports and historical peer-store recovery

Bisq 2 can run its own embedded Tor; the reviewed configuration assigns its SOCKS listener automatically. A separate Tor daemon on port 9050 does not mean Bisq uses it. A different port alone is not a fault, and port 8090 cannot be identified as a SOCKS listener without the process, configuration and connection role.

The peer-store workaround in issue 2826 was a conditional response to Bisq 2.1.0 Tor authentication and peer-connection failures. It named db/settings/tor_peer_group_store.protobuf under the actual Bisq2 data directory. It is not a universal reset for later releases. Close the application and preserve a full backup before any support-guided file change; do not delete the whole data directory or import an old attachment merely because initial network data is slow.

## Evidence / Sources

- https://bisq.wiki/Bisq_2
- https://bisq.wiki/Downloading_and_installing
- https://bisq.wiki/Dispute_Resolution_in_Bisq_2
- https://github.com/bisq-network/bisq2/issues

- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/network/tor/tor-common/src/main/java/bisq/network/tor/common/torrc/ClientTorrcGenerator.java
- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/network/tor/tor-common/src/main/java/bisq/network/tor/common/torrc/Torrc.java
- https://github.com/bisq-network/bisq2/issues/2826#issuecomment-2353496480
- https://github.com/bisq-network/bisq2/issues/2587#issuecomment-2276260039
- https://bisq.wiki/Bisq_2#Installation

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 340, 833, 975. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

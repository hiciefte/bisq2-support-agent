---
id: bisq2-startup-network-notifications
title: Bisq 2 startup, network, and notification troubleshooting
type: llm_wiki
page_type: support_playbook
status: proposed
protocol: bisq_easy
reviewed_by: null
reviewed_at: null
risk_level: medium
source_refs:
  - wiki:Bisq 2
  - wiki:Downloading and installing
  - wiki:Running Bisq in China
  - wiki:Dispute Resolution in Bisq 2
  - faq:3
  - faq:18
  - faq:38
  - faq:77
  - faq:99
  - faq:109
  - faq:694
  - faq:695
  - faq:708
  - faq:712
  - faq:1052
  - faq:1067
---
## Canonical Support Answer

For Bisq 2 startup, network-data, Tor, offerbook, notification, or mediation-button issues, first collect the exact symptom and version. Check that the user is on the latest supported Bisq 2 version, the operating-system clock is synchronized, and the network is not blocking Tor or Bisq traffic.

If Bisq 2 is stuck on requesting network data, has no offers, or cannot connect, do not apply Bisq 1 SPV wallet advice. Bisq 2/Bisq Easy does not use the Bisq 1 built-in wallet/SPV workflow. Start with version, clock, network/Tor reachability, and any current Bisq 2 issue-specific workaround. If a workaround involves replacing a protobuf or data file, require a full data-directory backup first and verify that the workaround applies to the user's version.

If notifications or open-trade badges look stale, ask whether the underlying trade is still visible and unresolved. For Bisq Easy trades already resolved outside the app, users may be able to reject/cancel the stale trade entry when both parties received what they expected. For a ghost notification with no open trade, clearing notifications from settings can be appropriate. If a real trade is still unresolved, use the trade or mediation flow instead of clearing the symptom.

If the mediation button is disabled, unavailable, or says no mediator is available, keep the user in the trade context and route them to support/open chats for mediator assistance. Do not tell them to repeatedly click failed mediation actions or to leave the trade unresolved after fiat has been sent.

Installation errors such as macOS `damaged` app warnings or Linux package signature questions should be answered from the current installation guide and release-signing instructions. Avoid giving stale version-specific terminal commands unless they match the current release files.

## Applies When

- Bisq 2 is stuck on `Requesting network data`.
- Bisq 2 has no offers or cannot connect to peers/Tor.
- The user reports system-time/network-reference warnings.
- The user asks about stale notifications, ghost open-trade badges, or no sound/visual notification.
- The user cannot request mediation or the mediation button is disabled.
- The user sees macOS damaged-app warnings or asks about current installation/signature verification.
- A support answer incorrectly suggests Bisq 1 SPV resync for a Bisq 2-only issue.

## Do Not Say

- Do not recommend Bisq 1 SPV resync for Bisq 2 startup, offerbook, or notification problems.
- Do not tell users to delete the Bisq 2 data directory before a backup exists.
- Do not promote file/protobuf replacement as generic advice without checking the current issue and version.
- Do not clear or reject a trade merely to hide a notification when fiat/BTC delivery is unresolved.
- Do not quote stale installer/signing commands for a different Bisq 2 release.

## Evidence / Sources

- `wiki:Bisq 2` documents Bisq 2 as a separate application and networked desktop client.
- `wiki:Downloading and installing` documents installation and platform-specific setup.
- `wiki:Running Bisq in China` provides network-restriction context.
- `wiki:Dispute Resolution in Bisq 2` documents mediation availability in Bisq 2.
- `faq:3` and `faq:712` cover macOS damaged/broken app installation issues.
- `faq:18`, `faq:38`, `faq:77`, and `faq:708` cover notifications, stale market data, and completed trade cleanup.
- `faq:99` and `faq:1052` cover requesting mediation and unavailable mediator handling.
- `faq:109`, `faq:694`, and `faq:695` cover network connection/Tor troubleshooting.
- `faq:1067` covers checking/updating to the latest version.

## Review Notes

- This page intentionally excludes API/developer-only offer-state questions and named incident workarounds unless they become durable support guidance.
- Review against current Bisq 2 release notes before activating, because startup/network workarounds can age quickly.

## Last Change Summary

Added one consolidated Bisq 2 troubleshooting page to absorb recurring production candidates without creating separate FAQ-like pages for network, notification, mediation-button, and installer symptoms.

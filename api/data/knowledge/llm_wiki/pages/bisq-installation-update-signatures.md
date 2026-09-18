---
id: bisq-installation-update-signatures
title: Bisq installation, updates and installer signature verification
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: all
risk_level: high
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
source_refs:
- https://bisq.network/downloads/
- https://bisq.wiki/Downloading_and_installing
- https://bisq.wiki/Updating_Bisq
- https://bisq.wiki/Backup
- https://www.gnupg.org/documentation/manuals/gnupg/Operational-GPG-Commands.html
- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/.github/workflows/build.yml
- https://github.com/bisq-network/bisq2/releases/tag/v2.0.3
- https://bisq.wiki/Bisq_2#Installation
- https://community.start9.com/t/restoring-history-from-account-on-laptop-to-bisq-on-start9/2138
- https://devblogs.microsoft.com/setup/resolving-prompts-for-source/
- https://learn.microsoft.com/en-us/troubleshoot/windows-client/application-management/missing-windows-installer-cache
- https://support.microsoft.com/en-US/Windows/Deployment/Install-Upgrade/fix-problems-that-block-programs-from-being-installed-or-removed
- https://github.com/bisq-network/bisq2/releases/tag/v2.1.13
- https://bisq.wiki/Downloading_and_installing#Verify_installer_file
- https://github.com/bisq-network/bisq/pull/7050
- https://github.com/bisq-network/bisq/blob/7731996dac80027f6ac77c4db1553fe65da8904c/gradle/libs.versions.toml
- https://github.com/bisq-network/bisq/blob/7731996dac80027f6ac77c4db1553fe65da8904c/desktop/build.gradle
- https://github.com/bisq-network/bisq/releases/tag/v1.9.14
- https://github.com/bisq-network/bisq/releases/tag/v1.10.8
- https://bisq.wiki/Running_Bisq_on_Tails#Upgrade_Bisq_to_the_latest_version
---
## Canonical Support Answer

Identify the application, operating system and architecture before selecting an installer. Use the official download page and release instructions. A normal same-application update installs the new application while preserving its separate data directory; preserve a complete backup first. A seed alone does not preserve Bisq 1 account and active-trade state. Moving from Bisq 1 to Bisq 2 is not this update process.

If an in-app update loops or leaves the old version running, download and verify the correct official installer and install it normally. A newer Debian package can replace the installed package without uninstalling first. On macOS, confirm the newly installed application is launched rather than an older copy or the mounted disk image. Verify the resulting version. Do not delete the data directory or migrate to a VM merely because an update failed.

If the updated application does not start, record the version, platform, architecture and exact startup error. Reinstalling the verified application over the existing installation can be a diagnostic step, not a promised cure. Exit code 1 alone does not establish the cause. Locate the application log using the actual data directory and share only relevant redacted errors through verified support. For macOS security warnings, use the release-specific official instructions after verifying the artifact; do not reuse a privileged command for a different bundle name or assume every crash is a quarantine problem.

## Signature verification

Obtain the installer, matching detached signature and expected signing-key information for that exact release. Verify the complete signer fingerprint against official references; signers can change. Importing a public key is not verification of an installer. Use `gpg --verify INSTALLER.asc INSTALLER` with the actual matching filenames, or the documented graphical equivalent. Check the result and any expiration or revocation warnings before installing.

A GPG Good signature result establishes that the file matches a signature made with the key. A key-not-certified warning concerns whether your local trust model authenticates that key's identity. It does not mean the key is absent, and changing local trust cannot authenticate it. Do not promise that importing one historical short key ID makes future downloads safe or automatically verified.

Downloading through Tor Browser is optional and distinct from Bisq's runtime networking. Tor can reduce some network exposure but does not authenticate the installer or guarantee anonymity; signature verification remains necessary.

## Platform coverage and package-managed updates

The reviewed Bisq 2 CI builds on Ubuntu 24.04 and releases supply a Debian package. Build coverage is not an exhaustive Linux desktop compatibility certification; manual installation on other distributions needs the appropriate release and architecture.

StartOS updates belong to its package update interface and configured registry, not a desktop installer copied into the service. Start9 support announced Bisq 1.9.18 in the community registry on 18 December 2024. That establishes historical availability, not a promise that an old package remains appropriate or available now.

## Windows Installer source prompts

A request for main.msi from an unavailable location is a Windows Installer source-resolution problem, potentially involving an earlier installation or missing installer cache. A valid PGP signature on a new Bisq download does not repair that state. Preserve Bisq data, record the requested product/version and source path, and use Microsoft’s version-appropriate installation troubleshooting or obtain the matching original package through its publisher. Do not download arbitrary MSI files or clear installer/wallet data.

## Version-specific macOS packaging and obsolete fixes

Use the product’s own official release instructions and the build for the Mac’s architecture. Bisq 2.1.13 specifically warns that Intel Macs can receive an incompatible Apple Silicon artifact through in-app updating; obtain the correct Intel build manually in that case. Quarantine instructions apply to the verified installed bundle and the corresponding security warning, not every crash or a running application’s network stall.

Historical packaging changes are not universal diagnoses. Bisq 1.9.16 added JavaCV platform dependencies for QR scanning, relevant to its larger download. Bisq 1.9.14 also had a re-uploaded macOS crash-fix binary. Neither fact proves the cause of an unseen error or justifies installing an obsolete hotfix now. Old releases are marked superseded, and downgrading a newer data directory can damage it. Preserve complete data and diagnose on a supported release rather than delete state or assume a particular old version is a cure.

## Evidence / Sources

- https://bisq.network/downloads/
- https://bisq.wiki/Downloading_and_installing
- https://bisq.wiki/Updating_Bisq
- https://bisq.wiki/Backup
- https://www.gnupg.org/documentation/manuals/gnupg/Operational-GPG-Commands.html

- https://github.com/bisq-network/bisq2/blob/ae3176e4431eeaef309aada264ff8a75616f21d7/.github/workflows/build.yml
- https://github.com/bisq-network/bisq2/releases/tag/v2.0.3
- https://bisq.wiki/Bisq_2#Installation
- https://community.start9.com/t/restoring-history-from-account-on-laptop-to-bisq-on-start9/2138
- https://devblogs.microsoft.com/setup/resolving-prompts-for-source/
- https://learn.microsoft.com/en-us/troubleshoot/windows-client/application-management/missing-windows-installer-cache
- https://support.microsoft.com/en-US/Windows/Deployment/Install-Upgrade/fix-problems-that-block-programs-from-being-installed-or-removed
- https://github.com/bisq-network/bisq2/releases/tag/v2.1.13
- https://bisq.wiki/Downloading_and_installing#Verify_installer_file
- https://github.com/bisq-network/bisq/pull/7050
- https://github.com/bisq-network/bisq/blob/7731996dac80027f6ac77c4db1553fe65da8904c/gradle/libs.versions.toml
- https://github.com/bisq-network/bisq/blob/7731996dac80027f6ac77c4db1553fe65da8904c/desktop/build.gradle
- https://github.com/bisq-network/bisq/releases/tag/v1.9.14
- https://github.com/bisq-network/bisq/releases/tag/v1.10.8
- https://bisq.wiki/Running_Bisq_on_Tails#Upgrade_Bisq_to_the_latest_version

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 407, 791, 875, 1079, 1151, 1495, 2088. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.

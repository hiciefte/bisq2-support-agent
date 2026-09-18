---
id: bisq2-profile-data-recovery
title: Bisq 2 local profile recovery and moving devices
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: bisq_easy
reviewed_by: ai-review:codex:knowledge-batch-20260918
reviewed_at: '2026-09-18T08:30:52.377693+00:00'
risk_level: high
source_refs:
- https://bisq.wiki/Data_directory
- https://bisq.wiki/Backup
- https://bisq.wiki/Automatic_backup
- https://github.com/bisq-network/bisq2/blob/main/common/src/main/java/bisq/common/platform/PlatformUtils.java
---
## Canonical Support Answer

A Bisq 2 profile depends on local application data. There is no central account login that restores the profile on a new computer. A new empty profile is a different identity, not recovery of the old reputation or trades.

Before experimenting, preserve complete copies of the current data directory, the old device's data and existing backups. Locate the actual directory using the installed application's directory-opening control. Depending on version this is exposed in Support/Resources or Settings/Utilities; do not substitute Bisq 1's Account > Backup menu automatically.

Usual desktop defaults are `%APPDATA%\Bisq2` on Windows, `~/.local/share/Bisq2` on Linux and `~/Library/Application Support/Bisq2` on macOS. A custom app name, launch option or packaged environment can change them. The `db` area contains profile state, but copying only `db/private` or one protobuf file is not a complete migration guarantee.

For a planned move, close Bisq 2 on both machines, back up any destination state, and copy the full source data directory into the correct destination without adding an extra nesting level. Start the destination and verify profile, reputation and trades. Use only one active copy of that identity afterward. Two computers running copied state do not synchronize changes and may interfere with each other's trades. A cross-platform copy does not itself solve Tails networking or persistence requirements.

If the profile disappears after an update, power failure or accidental new-profile creation, check the actual directory and preserved local backups before declaring it lost. Bisq 2 supports manual full-directory backups and automatic versioned storage-file backups. These are different recovery sources: automatic per-file versions are not necessarily a single consistent whole-profile snapshot. Preserve current state before selecting a documented, version-appropriate restore procedure with support.

Without surviving identity data or a usable backup, do not promise restoration of the old profile or its reputation. A Bisq 1 wallet seed or backup is not a Bisq 2 identity restore.

## Do Not Say

- Do not delete an apparently empty destination until its contents have been checked and preserved.
- Do not replace arbitrary database/protobuf files or overwrite newer trades with old data as a routine repair.
- Do not request seed words, private keys or an unredacted data directory in public support.

## Evidence / Sources

- https://bisq.wiki/Data_directory
- https://bisq.wiki/Backup
- https://bisq.wiki/Automatic_backup
- https://github.com/bisq-network/bisq2/blob/main/common/src/main/java/bisq/common/platform/PlatformUtils.java

## Review Notes

Independently reviewed by the parent AI reviewer after individual candidate review. Reviewer: `ai-review:codex:knowledge-batch-20260918`. Sources checked on 2026-09-18; verify release-sensitive behavior against the user's installed version.

## Last Change Summary

Preserved default paths and backup discovery, replaced deletion-first migration with preservation, and distinguished automatic per-file backups from complete consistent profile backups.

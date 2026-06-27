---
id: bisq2-profile-data-recovery
title: Bisq 2 profile and data recovery
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: bisq_easy
reviewed_by: suddenwhipvapor
reviewed_at: '2026-06-27'
risk_level: high
source_refs:
- wiki:Data directory
- wiki:Automatic backup script
- faq:13
- faq:713
- faq:877
- faq:1044
- faq:1114
---
## Canonical Support Answer

Bisq 2 profile recovery depends on local data exclusively. There is no central login server that can restore a lost profile. The important target is the Bisq 2 data directory, especially the `db` data for the profile. If the user has a backup, or an old device still has the original data directory, restore from that source instead of creating a new profile.

For a planned move to another device, close Bisq on both machines, copy the Bisq 2 data directory from the location on the old device to the correct OS-dependent location on the new one, then start Bisq on the new device. If the new device already created an empty profile, close Bisq 2, back up that new data directory if user wants to keep it, or, most likely, delete it if that is a brand new profile with no history/reputation, then replace it with the copied old data. After a successful move, avoid using the old instance and only use the new device with the current copy.

If the user created a new profile after losing the old one, check whether the backups folder or old data directory still contains a viable copy of the previous profile data. If there is no backup, and the old local data is gone, the profile is not recoverable, and any associated reputation is ultimately lost.

If a support workaround mentions a specific protobuf file, treat it as version/incident-specific. Do not tell users to delete or replace arbitrary protobuf/database files unless there is a current, source-backed procedure and the user has first made a full copy of the data directory.

When giving recovery advice, first prevent further damage: ask the user not to delete or overwrite existing Bisq data directories, and to make a copy before experimenting with restores.

Default data directory locations are as follows:
- Windows: `%USERPROFILE%\AppData\Roaming\Bisq2\`
- Linux: `/home/<username>/.local/share/Bisq2/`
- macOS: `/Users/<username>/Library/Application Support/Bisq2/`

The data directory contains a `backups` folder, to which versioned copies of the profile are automatically saved, and can be selectively restored to try and solve issues, after the current profile folder has been backed up.

## Applies When

- The user formatted, reinstalled, updated, or restored the app and lost a Bisq 2 profile.
- The app starts with a new/empty profile unexpectedly.
- The user asks which files matter for restoring profile state.
- The user wants to move a Bisq 2 account/profile to another device.
- The user created a new profile but wants the previous profile back.
- The user asks about a file-level recovery workaround for a corrupted profile or network-state file.

## Do Not Say

- Do not promise recovery without a backup or preserved data directory.
- Do not ask for seed words, private keys, or sensitive secrets in chat.
- Do not tell users to manually edit database/protobuf files as a routine first step.
- Do not confuse Bisq 2 profile recovery with Bisq 1 wallet seed recovery.
- Do not imply a central login or server-side account can restore the local profile.

## Evidence / Sources

- `wiki:Data directory` identifies Bisq's local application data location, OS-specific path patterns, and warnings against manually editing `db` files.
- `wiki:Automatic backup script` documents backup-oriented recovery context.
- `faq:13` states profile restore needs a copy of the Bisq 2 `db` folder from the data directory.
- `faq:713` says a missing profile without backup may be lost.
- `faq:877` says the backups folder may contain viable previous profile data.
- `faq:1044` says updates preserve the data directory, with backups as a precaution.
- `faq:1114` covers transferring Bisq accounts to a new device by moving the data directory.

## Review Notes

- The exact OS-specific Bisq 2 path should be confirmed from the user's environment before giving path-level commands.
- File-specific protobuf fixes should be reviewed against the current Bisq 2 issue/release before being promoted to durable support guidance.

## Last Change Summary

Added default data-directory locations, backups-folder guidance, and safer restore wording.

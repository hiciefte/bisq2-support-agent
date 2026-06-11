---
id: bisq2-profile-data-recovery
title: Bisq 2 profile and data recovery
type: llm_wiki
page_type: support_playbook
status: proposed
protocol: bisq_easy
reviewed_by: null
reviewed_at: null
risk_level: high
source_refs:
  - wiki:Data directory
  - wiki:Automatic backup script
  - faq:13
  - faq:713
  - faq:877
  - faq:1044
---
## Canonical Support Answer

Bisq profile recovery depends on local application data. The important target is the Bisq 2 data directory, especially the `db` data for the profile. If the user has a backup of the old data directory, they should restore from that backup instead of creating more new profiles.

If the user created a new profile after losing the old one, check whether the backups folder or old data directory still contains a viable copy of the previous profile data. If there is no backup and the old local data is gone, the profile may not be recoverable.

When giving recovery advice, first prevent further damage: ask the user not to delete or overwrite existing Bisq data directories, and to make a copy before experimenting with restores.

## Applies When

- The user formatted, reinstalled, updated, or restored the app and lost a Bisq 2 profile.
- The app starts with a new/empty profile unexpectedly.
- The user asks which files matter for restoring profile state.

## Do Not Say

- Do not promise recovery without a backup or preserved data directory.
- Do not ask for seed words, private keys, or sensitive secrets in chat.
- Do not tell users to manually edit database files.

## Evidence / Sources

- `wiki:Data directory` identifies Bisq's local application data location and warns against manually editing `db` files.
- `wiki:Automatic backup script` documents backup-oriented recovery context.
- `faq:13` states profile restore needs a copy of the Bisq2 `db` folder from the data directory.
- `faq:713` says a missing profile without backup may be lost.
- `faq:877` says the backups folder may contain viable previous profile data.
- `faq:1044` says updates preserve the data directory, with backups as a precaution.

## Review Notes

- The exact OS-specific Bisq 2 path should be confirmed from the user's environment before giving path-level commands.

## Last Change Summary

Converted from generated support playbook into internal LLM Wiki page; ready for local support-admin review.

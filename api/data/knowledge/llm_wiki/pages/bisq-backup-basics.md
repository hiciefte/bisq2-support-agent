---
id: bisq-backup-basics
title: Checking Bisq backup contents and preserving recovery data
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: all
risk_level: high
reviewed_by: ai-review:codex:knowledge-batch-20260918
reviewed_at: '2026-09-18T08:30:52.377693+00:00'
source_refs:
- https://bisq.wiki/Backup
- https://bisq.wiki/Backing_up_application_data
- https://bisq.wiki/Automatic_backup
- https://bisq.wiki/Data_directory
---
## Canonical Support Answer

A large first backup is not necessarily faulty. Application data can include network state and logs before the user enters payment details. Size and file count depend on the application version, data history and backup method; no universal megabyte or file-count threshold proves completeness.

Identify what made the backup and what it includes. A manual full-data-directory copy is different from a script that copies selected files or Bisq 2's versioned per-file automatic backups. Compare the intended contents with the actual source directory, preserve the original and older recovery points, and use the documented restore procedure for the same application.

Do not discard earlier backups just because the newest file is larger or a synchronization completed. A backup predating a trade cannot contain that later trade state. Protect backups as sensitive data because they may contain identity, account and wallet secrets. Before an update or recovery experiment, retain a complete current copy; wallet seed recovery alone is not complete application recovery.

## Evidence / Sources

- https://bisq.wiki/Backup
- https://bisq.wiki/Backing_up_application_data
- https://bisq.wiki/Automatic_backup
- https://bisq.wiki/Data_directory

## Review Notes

Independently reviewed by the parent AI reviewer after individual candidate review. Reviewer: `ai-review:codex:knowledge-batch-20260918`. Sources checked on 2026-09-18; verify release-sensitive behavior against the user's installed version.

## Last Change Summary

Added general backup-size guidance and distinguished backup mechanisms without inventing incremental/cumulative guarantees.

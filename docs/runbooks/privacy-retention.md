# Privacy Retention

The API applies one validated local retention window, from 1 through 30 days.
The scheduler runs the job at container start and daily. A dry run performs no
database writes, file rewrites, cache invalidation, or compaction.

## Store inventory

| Store | Retention action |
| --- | --- |
| Feedback, conversation context, reactions, ChatOps audit, and trust-monitor records | Delete out-of-window rows; anonymize an old parent only when a newer child still requires its key |
| Hashed channel-delivery canary reservations | Delete reservations older than two days, or the shorter configured privacy window, through the scheduled job and compact `feedback.db` |
| Escalations and consumed rating tokens | Delete every out-of-window row, including unresolved escalations |
| Training candidates, thread messages, state transitions, knowledge proposals, and review feedback | Delete out-of-window rows; anonymize old candidate or thread keys when a newer linked row remains |
| Learning review history | Remove individual out-of-window review entries; retain threshold aggregates |
| Translation cache | Delete expired or out-of-window rows and clear the in-memory tier |
| Matrix and Bisq processed-message state | Delete timestamped out-of-window identifiers while retaining current sync cursors |
| Legacy JSON, JSONL, CSV, and feedback exports | Atomically rewrite rows with parseable timestamps; preserve malformed or untimestamped rows for manual migration because their age cannot be proven |
| Obsolete personal-data SQLite files | Delete timestamped out-of-window rows and compact; preserve tables or rows without a supported timestamp for manual migration |
| Matrix session JSON and local crypto store | Rotate the whole session generation on the configured cadence; the integration reauthenticates when next used |
| Bind-mounted nginx and scheduler logs | Copy-truncate active logs using the previous successful run as their oldest-age boundary, delete expired rotations, and purge active logs when that boundary is missing or stale |
| Docker runtime logs | Apply the checked-in host policy through the human-run configuration script |
| Deployment data backups | Delete expired local backup sets as complete units; Workstream 5 governs encrypted off-host sets |

Reviewed FAQs and support playbooks may retain reviewed question and answer
text indefinitely; these knowledge stores do not retain structured source user,
room, message, reviewer, or conversation identifiers. Aggregate operational
metrics and threshold history may also remain.
The local job does not remove original messages from Matrix or Bisq, nor records
held by a configured model provider.
Legacy processed-ID files created before per-ID timestamps were introduced use
the file modification time as a conservative migration boundary. Those IDs can
remain for one additional configured window after upgrade. Malformed and
untimestamped legacy or corrupted rows can also remain beyond the automated
window; their store-age metric alerts when the row or containing artifact needs
operator review.
Bind-mounted logs use a private last-run marker to bound the age of each
copy-truncated rotation. On first use, or after a gap longer than the configured
window, the job purges active log contents because it cannot prove that every
line is still in-window.

## Run and verify

Preview the complete application job:

```bash
docker compose -f docker/docker-compose.yml exec -T scheduler \
  /scripts/privacy-retention.sh --dry-run
```

Run it immediately:

```bash
docker compose -f docker/docker-compose.yml exec -T scheduler \
  /scripts/privacy-retention.sh
```

Preview bind-mounted log rotation:

```bash
docker compose -f docker/docker-compose.yml exec -T scheduler \
  /scripts/rotate-retention-logs.sh --dry-run
```

The compatibility entry point `scripts/cleanup_old_data.sh` invokes the same
containerized job. It intentionally has no retention override; change the
validated deployment setting so public copy and enforcement stay aligned.

Check Docker runtime-log coverage without changing the host:

```bash
scripts/configure-runtime-log-retention.sh --check
scripts/configure-runtime-log-retention.sh --print
```

Installation requires a human to select the host's log-rotation configuration
target, run the script with `--apply`, and verify the host scheduler. The
application scheduler must never receive the Docker socket.

## Metrics and alerts

Inspect these series:

- `privacy_retention_rows_deleted_total{store}`
- `privacy_retention_rows_anonymized_total{store}`
- `privacy_retention_deleted_last{store}`
- `privacy_retention_oldest_age_seconds{store}`
- `privacy_retention_window_seconds{store}`
- `privacy_retention_last_success_timestamp_seconds{store}`
- `privacy_retention_log_last_success_timestamp_seconds`
- `privacy_retention_failures_total{store}`

`PrivacyRetentionWindowExceeded` means a store contains personal data beyond
its exported window. `PrivacyRetentionMetricsMissing` and
`PrivacyRetentionJobStale` independently detect absent telemetry and overdue
successes for each daily API store group. `PrivacyRetentionLogMetricsMissing`
and `PrivacyRetentionLogJobStale` apply the same split to the bind-mounted log
job through node-exporter. `MatrixAlertRelayRetentionMetricsMissing` and
`MatrixAlertRelayRetentionStale` cover the isolated relay session volume.
`PrivacyRetentionFailures` means the labeled store group failed while the job
continued with the remaining groups.

## Triage

1. Run a dry run and identify the failing allowlisted store label in API logs.
2. Confirm available disk space and database ownership without copying record
   contents into a ticket.
3. For SQLite lock failures, stop the conflicting maintenance task and rerun.
   A hidden per-database pending marker survives any post-commit checkpoint or
   compaction failure, so the next run retries even when no rows remain to
   delete.
4. For malformed or untimestamped legacy rows, migrate the timestamp from a
   trustworthy source or remove the artifact after a sanitized operator review.
   The automated job deliberately does not guess a row's age.
5. For Matrix rotation, confirm password authentication is configured. A fresh
   device/session after the retention boundary is expected.
6. For runtime logs, run the host script in check mode and have an operator
   verify the installed age policy and its daily execution.
7. Rerun the job and confirm both the oldest-age alert and stale-job alert
   clear.

Never restore expired personal records from a backup. During a restore, apply
retention before exposing the service and discard any backup set older than the
configured window unless a separately approved legal policy explicitly covers
that encrypted set.

## Human decisions

- Approve whole-generation Matrix session and crypto-store rotation, accepting
  fresh device/key history at each retention boundary.
- Select, install, and periodically verify the production host's Docker
  runtime-log policy.
- Approve the public wording about upstream Matrix/Bisq messages and configured
  model-provider records.
- Choose the low-traffic maintenance window for compaction and rehearse the
  job before production activation.

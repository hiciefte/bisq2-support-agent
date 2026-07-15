# Scheduler heartbeat stale

## Impact

Periodic feedback, wiki, readiness, reconciliation, or training jobs may no
longer be running even if the scheduler process still exists.

## Confirm

1. Check scheduler Docker health and recent cron logs.
2. Inspect `scheduler_heartbeat_timestamp_seconds` and confirm whether it is
   absent, zero, or older than three minutes.
3. Confirm node-exporter and its textfile collector are healthy before assuming
   cron itself has stopped.

## Triage

1. Verify the heartbeat script is mounted and can atomically update the shared
   metrics directory.
2. Check cron process state and the most recent failures for each scheduled
   job.
3. Restart through the repository lifecycle scripts if the scheduler is stuck.
   Do not grant Docker socket access or administrator credentials to it.

## Recovery

The heartbeat timestamp must refresh each minute for at least five minutes, and
the scheduler Docker health check and alert must both recover.

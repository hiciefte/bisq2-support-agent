#!/bin/bash
set -euo pipefail

metrics_dir="${SCHEDULER_METRICS_DIR:-/var/lib/node_exporter/textfile_collector}"
metrics_file="$metrics_dir/scheduler-heartbeat.prom"
temporary_file=""

cleanup() {
    if [ -n "$temporary_file" ] && [ -f "$temporary_file" ]; then
        rm -f "$temporary_file"
    fi
}
trap cleanup EXIT

mkdir -p "$metrics_dir"
temporary_file=$(mktemp "$metrics_dir/.scheduler-heartbeat.XXXXXX")
timestamp=$(date +%s)

# A canonical Staff trial deliberately holds these six entries, including
# retention, until the next authorized lifecycle replaces the guard. Observe
# the actual crontab; never infer a hold from an environment flag or its age.
# Invalid, partial or duplicated guards cannot suppress retention alerts.
crontab_file="${SCHEDULER_CRONTAB_FILE:-/etc/crontabs/root}"
hold_state="0 0 1"
if [ -r "$crontab_file" ]; then
    hold_state=$(awk '
        BEGIN {
            schedules[1] = "@reboot"
            schedules[2] = "0 0 * * 1"
            schedules[3] = "0 */12 * * *"
            schedules[4] = "@reboot"
            schedules[5] = "0 2 * * *"
            schedules[6] = "30 2 * * *"
            jobs[1] = jobs[2] = "/scripts/process-feedback.sh >> /var/log/cron/feedback.log 2>&1"
            jobs[3] = "/scripts/poll-matrix.sh >> /var/log/cron/matrix-poll.log 2>&1"
            jobs[4] = jobs[5] = "/scripts/privacy-retention.sh >> /var/log/cron/privacy-retention.log 2>&1"
            jobs[6] = "/scripts/rotate-retention-logs.sh >> /var/log/cron/privacy-retention.log 2>&1"
        }
        /^[[:space:]]*(#|$)/ { next }
        /\/scripts\/(process-feedback|poll-matrix|privacy-retention|rotate-retention-logs)\.sh/ {
            relevant++
            if ($0 ~ /(^|[[:space:]])false[[:space:]]*&&/) attempted = 1
            matched = 0
            for (i = 1; i <= 6; i++) {
                prefix = schedules[i] " false && : "
                if (index($0, prefix) != 1) continue
                split(substr($0, length(prefix) + 1), fields, " ")
                id = fields[1]
                cutoff = fields[2]
                if (id !~ /^[A-Za-z0-9][A-Za-z0-9_-]*$/ || length(id) > 80) continue
                if (cutoff !~ /^[0-9]+$/ || length(cutoff) != 10 || cutoff + 0 <= 0) continue
                if ($0 != prefix id " " cutoff " && " jobs[i]) continue
                if (seen[i]++) invalid = 1
                if (guard_id != "" && (guard_id "" != id "" || guard_cutoff != cutoff)) invalid = 1
                guard_id = id
                guard_cutoff = cutoff
                matched = 1
                break
            }
            if (!matched) invalid = 1
        }
        END {
            count = 0
            for (i = 1; i <= 6; i++) if (seen[i] == 1) count++
            active = attempted && !invalid && count == 6 && relevant == 6
            printf "%d %s %d\n", active, active ? guard_cutoff : "0", attempted && !active
        }
    ' "$crontab_file") || hold_state="0 0 1"
fi
read -r hold_active hold_cutoff hold_invalid <<< "$hold_state"

{
    echo '# HELP scheduler_heartbeat_timestamp_seconds Unix timestamp of the latest scheduler cron heartbeat.'
    echo '# TYPE scheduler_heartbeat_timestamp_seconds gauge'
    echo "scheduler_heartbeat_timestamp_seconds $timestamp"
    echo '# HELP scheduler_retention_hold_active Whether all six canonical Staff-trial cron guards are present and consistent.'
    echo '# TYPE scheduler_retention_hold_active gauge'
    echo "scheduler_retention_hold_active $hold_active"
    echo '# HELP scheduler_retention_hold_cutoff_timestamp_seconds Original trial cutoff; the guard deliberately remains after this time.'
    echo '# TYPE scheduler_retention_hold_cutoff_timestamp_seconds gauge'
    echo "scheduler_retention_hold_cutoff_timestamp_seconds $hold_cutoff"
    echo '# HELP scheduler_retention_hold_invalid Whether a Staff-trial hold is malformed or its crontab cannot be read.'
    echo '# TYPE scheduler_retention_hold_invalid gauge'
    echo "scheduler_retention_hold_invalid $hold_invalid"
    echo '# HELP scheduler_retention_hold_observed_timestamp_seconds Unix timestamp of the last local crontab hold inspection.'
    echo '# TYPE scheduler_retention_hold_observed_timestamp_seconds gauge'
    echo "scheduler_retention_hold_observed_timestamp_seconds $timestamp"
} > "$temporary_file"

chmod 0644 "$temporary_file"
mv "$temporary_file" "$metrics_file"
temporary_file=""
touch /tmp/scheduler-heartbeat

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

{
    echo '# HELP scheduler_heartbeat_timestamp_seconds Unix timestamp of the latest scheduler cron heartbeat.'
    echo '# TYPE scheduler_heartbeat_timestamp_seconds gauge'
    echo "scheduler_heartbeat_timestamp_seconds $timestamp"
} > "$temporary_file"

chmod 0644 "$temporary_file"
mv "$temporary_file" "$metrics_file"
temporary_file=""
touch /tmp/scheduler-heartbeat

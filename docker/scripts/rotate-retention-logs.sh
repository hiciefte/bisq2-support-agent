#!/bin/bash
set -euo pipefail

retention_days="${DATA_RETENTION_DAYS:-30}"
metrics_dir="${SCHEDULER_METRICS_DIR:-/var/lib/node_exporter/textfile_collector}"
log_base="${RETENTION_LOG_BASE:-/var/log}"
dry_run=false

if [ "${1:-}" = "--dry-run" ]; then
    dry_run=true
elif [ "$#" -gt 0 ]; then
    echo "Usage: rotate-retention-logs.sh [--dry-run]" >&2
    exit 2
fi

case "$retention_days" in
    ''|*[!0-9]*)
        echo "DATA_RETENTION_DAYS must be an integer" >&2
        exit 2
        ;;
esac
if [ "$retention_days" -lt 1 ] || [ "$retention_days" -gt 30 ]; then
    echo "DATA_RETENTION_DAYS must be between 1 and 30" >&2
    exit 2
fi

case "$log_base" in
    /*) ;;
    *)
        echo "RETENTION_LOG_BASE must be absolute" >&2
        exit 2
        ;;
esac
case "/${log_base}/" in
    *"/../"*|*"/./"*)
        echo "RETENTION_LOG_BASE must not contain traversal segments" >&2
        exit 2
        ;;
esac
if [ -L "$log_base" ]; then
    echo "Refusing symlinked log base" >&2
    exit 1
fi

log_roots=("$log_base/cron" "$log_base/retention/nginx")
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
now=$(date +%s)
cutoff=$((now - retention_days * 86400))
deleted=0
pending_marker=""
temporary_file=""

cleanup() {
    [ -z "$pending_marker" ] || rm -f -- "$pending_marker"
    [ -z "$temporary_file" ] || rm -f -- "$temporary_file"
}
trap cleanup EXIT

file_mtime() {
    stat -c %Y "$1" 2>/dev/null || stat -f %m "$1"
}

for root in "${log_roots[@]}"; do
    [ -d "$root" ] || continue
    if [ -L "$root" ]; then
        echo "Refusing symlinked log root" >&2
        exit 1
    fi

    run_marker="$root/.privacy-retention-last-run"
    prior_run_is_bounded=false
    if [ -L "$run_marker" ]; then
        echo "Refusing symlinked retention marker" >&2
        exit 1
    fi
    if [ -f "$run_marker" ]; then
        prior_run=$(file_mtime "$run_marker")
        if [ "$prior_run" -ge "$cutoff" ] && [ "$prior_run" -le "$now" ]; then
            prior_run_is_bounded=true
        fi
    fi
    if [ "$dry_run" = false ]; then
        pending_marker=$(mktemp "$root/.privacy-retention-last-run.XXXXXX")
        printf '%s\n' "$now" > "$pending_marker"
        chmod 0600 "$pending_marker"
    fi

    while IFS= read -r -d '' active_log; do
        if [ -L "$active_log" ]; then
            echo "Refusing symlinked log file" >&2
            exit 1
        fi
        [ -s "$active_log" ] || continue
        rotated_log="${active_log}.${timestamp}"
        if [ "$prior_run_is_bounded" = false ]; then
            if [ "$dry_run" = true ]; then
                printf 'Would purge unbounded active log %s\n' "$(basename "$active_log")"
            else
                : > "$active_log"
            fi
            deleted=$((deleted + 1))
            continue
        fi
        if [ "$dry_run" = true ]; then
            printf 'Would rotate %s\n' "$(basename "$active_log")"
        else
            cp "$active_log" "$rotated_log"
            touch -r "$run_marker" "$rotated_log"
            : > "$active_log"
            chmod 0600 "$rotated_log"
        fi
    done < <(find "$root" -maxdepth 1 -type f -name '*.log' -print0)

    while IFS= read -r -d '' old_log; do
        if [ -L "$old_log" ]; then
            echo "Refusing symlinked rotated log" >&2
            exit 1
        fi
        modified=$(file_mtime "$old_log")
        if [ "$modified" -ge "$cutoff" ]; then
            continue
        fi
        if [ "$dry_run" = true ]; then
            printf 'Would remove %s\n' "$(basename "$old_log")"
        else
            rm -f -- "$old_log"
        fi
        deleted=$((deleted + 1))
    done < <(
        find "$root" -maxdepth 1 -type f -name '*.log.*' -print0
    )

    if [ "$dry_run" = false ]; then
        mv "$pending_marker" "$run_marker"
        pending_marker=""
    fi
done

if [ "$dry_run" = true ]; then
    exit 0
fi

oldest_age=0
success_time=$(date +%s)
for root in "${log_roots[@]}"; do
    [ -d "$root" ] || continue
    while IFS= read -r -d '' retained_log; do
        modified=$(file_mtime "$retained_log")
        age=$((now - modified))
        if [ "$age" -gt "$oldest_age" ]; then
            oldest_age="$age"
        fi
    done < <(find "$root" -maxdepth 1 -type f -name '*.log*' -print0)
done

mkdir -p "$metrics_dir"
temporary_file=$(mktemp "$metrics_dir/.privacy-retention-logs.XXXXXX")
{
    echo '# HELP privacy_retention_log_files_deleted_last Log files deleted by the latest retention run.'
    echo '# TYPE privacy_retention_log_files_deleted_last gauge'
    echo "privacy_retention_log_files_deleted_last ${deleted}"
    echo '# HELP privacy_retention_oldest_age_seconds Age of the oldest retained personal-data record.'
    echo '# TYPE privacy_retention_oldest_age_seconds gauge'
    echo "privacy_retention_oldest_age_seconds{store=\"application_logs\"} ${oldest_age}"
    echo '# HELP privacy_retention_window_seconds Maximum configured age for a personal-data store.'
    echo '# TYPE privacy_retention_window_seconds gauge'
    echo "privacy_retention_window_seconds{store=\"application_logs\"} $((retention_days * 86400))"
    echo '# HELP privacy_retention_log_last_success_timestamp_seconds Unix timestamp of the latest successful bind-mounted log-retention run.'
    echo '# TYPE privacy_retention_log_last_success_timestamp_seconds gauge'
    echo "privacy_retention_log_last_success_timestamp_seconds ${success_time}"
} > "$temporary_file"
chmod 0644 "$temporary_file"
mv "$temporary_file" "$metrics_dir/privacy-retention-logs.prom"
temporary_file=""
trap - EXIT

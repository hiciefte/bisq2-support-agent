#!/bin/bash
set -euo pipefail

mode="${1:---check}"
target_file="${2:-}"
retention_days="${DATA_RETENTION_DAYS:-30}"

usage() {
    echo "Usage: configure-runtime-log-retention.sh [--check | --print | --apply TARGET_FILE]"
}

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

docker_root=$(docker info --format '{{.DockerRootDir}}')
if [ -z "$docker_root" ] || [ ! -d "$docker_root" ]; then
    echo "Could not determine the Docker data root" >&2
    exit 1
fi

render_policy() {
    printf '%s\n' "${docker_root}/containers/*/*-json.log {"
    printf '%s\n' '    daily'
    printf '%s\n' "    rotate ${retention_days}"
    printf '%s\n' "    maxage ${retention_days}"
    printf '%s\n' '    missingok'
    printf '%s\n' '    compress'
    printf '%s\n' '    delaycompress'
    printf '%s\n' '    copytruncate'
    printf '%s\n' '    notifempty'
    printf '%s\n' '}'
}

case "$mode" in
    --check)
        echo "Docker runtime logs require a host-managed age policy."
        echo "Run --print for the proposed policy or --apply with a human-selected target."
        ;;
    --print)
        render_policy
        ;;
    --apply)
        if [ -z "$target_file" ]; then
            usage >&2
            exit 2
        fi
        if [ "$(id -u)" -ne 0 ]; then
            echo "--apply must be run with host administrator privileges" >&2
            exit 1
        fi
        if [ -L "$target_file" ]; then
            echo "Refusing a symlink target" >&2
            exit 1
        fi
        temporary_file=$(mktemp "${target_file}.XXXXXX")
        trap 'rm -f "$temporary_file"' EXIT
        render_policy > "$temporary_file"
        chmod 0644 "$temporary_file"
        mv "$temporary_file" "$target_file"
        trap - EXIT
        logrotate --debug "$target_file"
        echo "Runtime-log retention policy installed; schedule and execute logrotate separately."
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac

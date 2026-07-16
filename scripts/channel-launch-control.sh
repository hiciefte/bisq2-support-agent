#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  channel-launch-control.sh status
  channel-launch-control.sh kill
  channel-launch-control.sh enable
  channel-launch-control.sh shadow CHANNEL on|off
  channel-launch-control.sh canary CHANNEL off
  channel-launch-control.sh canary CHANNEL on HOURLY_LIMIT DAILY_LIMIT

Required environment:
  ADMIN_BASE_URL  Protected API base URL (include the gateway /api prefix)
  ADMIN_API_KEY   Admin API credential (never printed)

Safety guard:
  CONFIRM_AUTONOMOUS_DELIVERY=YES is required for the enable command.
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

require_channel() {
    case "$1" in
        matrix | bisq2) ;;
        *) die "Unsupported channel: $1" ;;
    esac
}

require_nonnegative_integer() {
    [[ "$1" =~ ^[0-9]+$ ]] || die "$2 must be a non-negative integer"
}

api_request() {
    local method=$1
    local path=$2
    local body=${3:-}
    local args=(
        --fail
        --silent
        --show-error
        --request "$method"
    )
    if [[ -n "$body" ]]; then
        args+=(--data "$body")
    fi
    printf 'X-API-KEY: %s\nContent-Type: application/json\n' "$ADMIN_API_KEY" | \
        env -u ADMIN_API_KEY curl "${args[@]}" --header @- \
            "${ADMIN_BASE_URL%/}${path}"
}

command_name=${1:-}
if [[ -z "$command_name" || "$command_name" == "-h" || "$command_name" == "--help" ]]; then
    usage
    exit 0
fi

require_command curl
require_command env
require_command jq
[[ -n "${ADMIN_BASE_URL:-}" ]] || die "ADMIN_BASE_URL is required"
[[ -n "${ADMIN_API_KEY:-}" ]] || die "ADMIN_API_KEY is required"
[[ "$ADMIN_API_KEY" != *$'\n'* && "$ADMIN_API_KEY" != *$'\r'* ]] || \
    die "ADMIN_API_KEY must not contain line breaks"

case "$command_name" in
    status)
        [[ $# -eq 1 ]] || die "status takes no arguments"
        api_request GET "/admin/channels/launch-control/global" | jq .
        api_request GET "/admin/channels/launch-control" | jq .
        ;;
    kill)
        [[ $# -eq 1 ]] || die "kill takes no arguments"
        api_request PUT "/admin/channels/launch-control/global" \
            '{"autonomous_delivery_enabled":false}' | jq .
        ;;
    enable)
        [[ $# -eq 1 ]] || die "enable takes no arguments"
        [[ "${CONFIRM_AUTONOMOUS_DELIVERY:-}" == "YES" ]] || \
            die "Set CONFIRM_AUTONOMOUS_DELIVERY=YES after completing the launch checklist"
        api_request PUT "/admin/channels/launch-control/global" \
            '{"autonomous_delivery_enabled":true}' | jq .
        ;;
    shadow)
        [[ $# -eq 3 ]] || die "shadow requires CHANNEL and on|off"
        channel=$2
        state=$3
        require_channel "$channel"
        case "$state" in
            on) enabled=true ;;
            off) enabled=false ;;
            *) die "shadow state must be on or off" ;;
        esac
        body=$(jq -cn --argjson enabled "$enabled" '{shadow_mode:$enabled}')
        api_request PUT "/admin/channels/launch-control/${channel}" "$body" | jq .
        ;;
    canary)
        [[ $# -ge 3 ]] || die "canary requires CHANNEL and on|off"
        channel=$2
        state=$3
        require_channel "$channel"
        if [[ "$state" == "off" ]]; then
            [[ $# -eq 3 ]] || die "canary off takes no limits"
            body='{"canary_enabled":false,"canary_hourly_limit":0,"canary_daily_limit":0}'
        elif [[ "$state" == "on" ]]; then
            [[ $# -eq 5 ]] || die "canary on requires hourly and daily limits"
            hourly=$4
            daily=$5
            require_nonnegative_integer "$hourly" "hourly limit"
            require_nonnegative_integer "$daily" "daily limit"
            (( hourly <= daily )) || die "hourly limit must not exceed daily limit"
            body=$(jq -cn \
                --argjson hourly "$hourly" \
                --argjson daily "$daily" \
                '{canary_enabled:true,canary_hourly_limit:$hourly,canary_daily_limit:$daily}')
        else
            die "canary state must be on or off"
        fi
        api_request PUT "/admin/channels/launch-control/${channel}" "$body" | jq .
        ;;
    *)
        usage >&2
        die "Unknown command: $command_name"
        ;;
esac

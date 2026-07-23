#!/bin/bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
DOCKER_DIR="$PROJECT_ROOT/docker"
COMPOSE_FILE="docker-compose.yml"

# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
setup_colors
source_deploy_paths "/etc/bisq-support/deploy.env" >&2 || true

assume_yes=false
case "${1:-}" in
    --yes|-y)
        assume_yes=true
        ;;
    --help|-h)
        echo "Usage: $0 [--yes]"
        echo "Fire, verify, and resolve a synthetic Matrix delivery alert."
        exit 0
        ;;
    "")
        ;;
    *)
        log_error "Unknown argument: $1"
        exit 2
        ;;
esac

if [ "$assume_yes" != "true" ]; then
    read -r -p "Send a synthetic alert to the configured staff alert room? [y/N] " confirmation
    case "$confirmation" in
        y|Y|yes|YES)
            ;;
        *)
            log_warning "Alert delivery drill cancelled"
            exit 1
            ;;
    esac
fi

check_required_commands docker jq awk
check_docker_daemon
check_docker_compose
pin_existing_compose_project \
    "$DOCKER_DIR" "$COMPOSE_FILE" existing

timeout_seconds="${DRILL_TIMEOUT_SECONDS:-120}"
if ! [[ "$timeout_seconds" =~ ^[0-9]+$ ]] || [ "$timeout_seconds" -lt 10 ]; then
    log_error "DRILL_TIMEOUT_SECONDS must be an integer of at least 10"
    exit 2
fi

read_notification_counter() {
    local metric_name="$1"
    run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" \
        exec -T alertmanager wget -qO- http://localhost:9093/metrics \
        | awk -v metric_name="$metric_name" '
            index($1, metric_name "{") == 1 && /receiver="matrix-drill"/ {
                total += $NF
            }
            END { printf "%.0f\n", total + 0 }
        '
}

post_alert_payload() {
    local payload="$1"
    run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" \
        exec -T api curl --fail --silent --show-error --max-time 10 \
        --request POST \
        --header "Content-Type: application/json" \
        --data-binary "$payload" \
        http://alertmanager:9093/api/v2/alerts >/dev/null
}

drill_id="drill-$(date -u +%Y%m%dT%H%M%SZ)-$$"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
alert_active=false

# ShellCheck cannot infer that EXIT traps invoke their callback.
# shellcheck disable=SC2317,SC2329
resolve_drill_alert() {
    if [ "$alert_active" != "true" ]; then
        return
    fi

    local ended_at
    local payload
    ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    payload=$(jq -cn \
        --arg drill_id "$drill_id" \
        --arg started_at "$started_at" \
        --arg ended_at "$ended_at" \
        '[{
            labels: {
                alertname: "AlertDeliveryDrill",
                severity: "warning",
                component: "monitoring",
                drill_id: $drill_id
            },
            annotations: {
                summary: "Synthetic alert delivery drill resolved",
                description: "An operator-requested alert delivery drill has completed."
            },
            startsAt: $started_at,
            endsAt: $ended_at
        }]')
    if ! post_alert_payload "$payload"; then
        log_warning "Synthetic drill alert could not be resolved automatically"
    fi
    alert_active=false
}
trap resolve_drill_alert EXIT

run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" \
    exec -T alertmanager wget -qO- http://localhost:9093/-/ready >/dev/null
run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" \
    exec -T api curl --fail --silent --show-error --max-time 5 \
    http://matrix-alert-relay:8000/ready >/dev/null

notifications_before=$(read_notification_counter alertmanager_notifications_total)
failures_before=$(read_notification_counter alertmanager_notifications_failed_total)

firing_payload=$(jq -cn \
    --arg drill_id "$drill_id" \
    --arg started_at "$started_at" \
    '[{
        labels: {
            alertname: "AlertDeliveryDrill",
            severity: "warning",
            component: "monitoring",
            drill_id: $drill_id
        },
        annotations: {
            summary: "Synthetic alert delivery drill",
            description: "An operator requested an end-to-end alert delivery check."
        },
        startsAt: $started_at
    }]')

log_info "Sending synthetic alert delivery drill"
post_alert_payload "$firing_payload"
alert_active=true

deadline=$((SECONDS + timeout_seconds))
while [ "$SECONDS" -lt "$deadline" ]; do
    notifications_after=$(read_notification_counter alertmanager_notifications_total)
    failures_after=$(read_notification_counter alertmanager_notifications_failed_total)
    notification_delta=$((notifications_after - notifications_before))
    failure_delta=$((failures_after - failures_before))
    successful_delta=$((notification_delta - failure_delta))

    if [ "$successful_delta" -ge 1 ]; then
        log_success "Alertmanager, the authenticated relay, and Matrix confirmed delivery"
        exit 0
    fi
    sleep 5
done

log_error "Alert delivery was not confirmed within ${timeout_seconds} seconds"
exit 1

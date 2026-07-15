#!/bin/bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
PROMETHEUS_CONFIG_DIR="$PROJECT_ROOT/docker/prometheus"

docker run --rm \
    --entrypoint promtool \
    --volume "$PROMETHEUS_CONFIG_DIR:/etc/prometheus:ro" \
    prom/prometheus:latest \
    check config /etc/prometheus/prometheus.yml

docker run --rm \
    --entrypoint promtool \
    --volume "$PROMETHEUS_CONFIG_DIR:/etc/prometheus:ro" \
    prom/prometheus:latest \
    check rules /etc/prometheus/alert_rules.yml

docker run --rm \
    --volume "$PROMETHEUS_CONFIG_DIR/blackbox.yml:/etc/blackbox_exporter/config.yml:ro" \
    prom/blackbox-exporter:v0.25.0 \
    --config.file=/etc/blackbox_exporter/config.yml \
    --config.check

docker run --rm \
    --entrypoint /bin/amtool \
    --volume "$PROJECT_ROOT/docker/alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro" \
    prom/alertmanager:v0.27.0 \
    check-config /etc/alertmanager/alertmanager.yml

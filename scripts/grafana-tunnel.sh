#!/bin/bash
set -Eeuo pipefail

# Open a local-only SSH tunnel to production Grafana.
# The remote Grafana port is intentionally bound to 127.0.0.1 on the host.

usage() {
    cat <<'EOF'
Usage:
  scripts/grafana-tunnel.sh <ssh-target>
  GRAFANA_SSH_TARGET=<ssh-target> scripts/grafana-tunnel.sh

Options via environment:
  GRAFANA_LOCAL_PORT   Local loopback port to bind. Default: 3001
  GRAFANA_REMOTE_HOST  Remote host visible from SSH target. Default: 127.0.0.1
  GRAFANA_REMOTE_PORT  Remote Grafana port. Default: 3001

Examples:
  scripts/grafana-tunnel.sh production-host
  GRAFANA_LOCAL_PORT=13001 scripts/grafana-tunnel.sh root@example-host

Browser:
  http://127.0.0.1:3001/grafana/

Grafana API / MCP base URL while the tunnel is running:
  http://127.0.0.1:3001
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

if [ "$#" -gt 1 ]; then
    usage >&2
    exit 64
fi

ssh_target="${1:-${GRAFANA_SSH_TARGET:-}}"
local_port="${GRAFANA_LOCAL_PORT:-3001}"
remote_host="${GRAFANA_REMOTE_HOST:-127.0.0.1}"
remote_port="${GRAFANA_REMOTE_PORT:-3001}"

if [ -z "$ssh_target" ]; then
    echo "Error: missing SSH target." >&2
    usage >&2
    exit 64
fi

validate_port() {
    local name="$1"
    local value="$2"

    if ! [[ "$value" =~ ^[0-9]+$ ]] || [ "$value" -lt 1 ] || [ "$value" -gt 65535 ]; then
        echo "Error: $name must be a TCP port between 1 and 65535." >&2
        exit 64
    fi
}

validate_port "GRAFANA_LOCAL_PORT" "$local_port"
validate_port "GRAFANA_REMOTE_PORT" "$remote_port"

if ! command -v ssh >/dev/null 2>&1; then
    echo "Error: ssh is required but was not found in PATH." >&2
    exit 127
fi

echo "Opening Grafana tunnel:"
echo "  local:  http://127.0.0.1:${local_port}"
echo "  remote: ${remote_host}:${remote_port} via ${ssh_target}"
echo ""
echo "Browser URL: http://127.0.0.1:${local_port}/grafana/"
echo "MCP/API URL: http://127.0.0.1:${local_port}"
echo "Press Ctrl-C to close the tunnel."

exec ssh \
    -N \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -L "127.0.0.1:${local_port}:${remote_host}:${remote_port}" \
    "$ssh_target"

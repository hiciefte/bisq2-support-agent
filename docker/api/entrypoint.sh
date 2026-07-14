#!/bin/bash
set -e

echo "=== Bisq Support API Entrypoint ==="

# shellcheck source=../scripts/lib/runtime-secret.sh
source /runtime-secret.sh

if [ -d "/run/bisq-secrets/scheduler" ]; then
    load_runtime_secret_from_file \
        "SCHEDULER_API_TOKEN" \
        "/run/bisq-secrets/scheduler/scheduler_api_token"
fi

if [ -d "/run/bisq-secrets/alertmanager" ]; then
    load_runtime_secret_from_file \
        "ALERTMANAGER_WEBHOOK_SECRET" \
        "/run/bisq-secrets/alertmanager/alertmanager_webhook_secret"
fi

# Fix app directory permissions
if [ -d "/app" ]; then
    echo "Fixing /app directory permissions..."
    chown -R bisq-support:bisq-support /app || true
    echo "✓ /app permissions fixed"
fi

# Fix data directory permissions (critical for database writes)
if [ -d "/data" ]; then
    echo "Fixing /data directory permissions..."
    chown -R bisq-support:bisq-support /data || true
    echo "✓ /data permissions fixed"
fi

echo "=== Starting application as bisq-support user (UID 1001) ==="

# Drop privileges and execute the main command as bisq-support user
exec gosu bisq-support "$@"

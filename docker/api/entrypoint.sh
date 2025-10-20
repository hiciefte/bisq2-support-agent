#!/bin/bash
set -e

echo "=== Bisq Support API Entrypoint ==="

# Note: /data directory permissions are handled via UID mapping
# Container UID 1001 (bisq-support) maps to host UID 1001
# No explicit permission changes needed for bind-mounted directories

# Fix app directory permissions
if [ -d "/app" ]; then
    echo "Fixing /app directory permissions..."
    chown -R bisq-support:bisq-support /app || true
    echo "✓ /app permissions fixed"
fi

echo "=== Starting application as bisq-support user (UID 1001) ==="

# Drop privileges and execute the main command as bisq-support user
exec gosu bisq-support "$@"

#!/bin/bash
set -e

echo "=== Bisq Support API Entrypoint ==="
echo "Fixing file permissions for bisq-support user (UID 1001)..."

# Fix ownership of all data files to bisq-support user
# This prevents "Permission denied" errors when the API tries to write to files
# that were created by deployment scripts running as root
if [ -d "/data" ]; then
    echo "Fixing /data directory permissions..."
    chown -R bisq-support:bisq-support /data || true
    chmod -R u+rw /data || true
    echo "✓ /data permissions fixed"
fi

# Fix app directory permissions
if [ -d "/app" ]; then
    chown -R bisq-support:bisq-support /app || true
    echo "✓ /app permissions fixed"
fi

echo "=== Starting application as bisq-support user (UID 1001) ==="

# Drop privileges and execute the main command as bisq-support user
exec gosu bisq-support "$@"

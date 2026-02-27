#!/bin/bash

# Exit on error
set -e

# Ensure the base data directory exists for the Java app
mkdir -p /opt/bisq2/data
chown bisq-support:bisq-support /opt/bisq2/data

# Copy the deployment-specific config to bisq.conf in the data directory
# This allows overriding defaults from the JAR's http_api_app.conf
CONFIG_SOURCE_FILE="/opt/bisq2/config/http_api_app.conf"
CONFIG_TARGET_FILE="/opt/bisq2/data/bisq.conf"

if [ -f "$CONFIG_SOURCE_FILE" ]; then
    echo "Copying custom configuration from $CONFIG_SOURCE_FILE to $CONFIG_TARGET_FILE..."
    cp "$CONFIG_SOURCE_FILE" "$CONFIG_TARGET_FILE"
    chown bisq-support:bisq-support "$CONFIG_TARGET_FILE"
    echo "Custom configuration copied."
else
    echo "Warning: Custom configuration source file $CONFIG_SOURCE_FILE not found. Using defaults from JAR or existing bisq.conf."
fi

# Tor startup/wait/config logic removed - Java application will handle embedded Tor.

echo "Starting Bisq2 API Application as user bisq-support..."
# Keep --data-dir as it seems to affect logging and is used by ApplicationService to find bisq.conf.
# Use config override for local/dev chat rate-limit behavior when needed.
BISQ_USER_RATE_LIMIT_ENABLED="${BISQ_USER_RATE_LIMIT_ENABLED:-true}"
exec gosu bisq-support /opt/bisq2/app/bin/api-app \
  --data-dir="$BISQ_DATA_DIR" \
  --application.user.rateLimitEnabled="$BISQ_USER_RATE_LIMIT_ENABLED"

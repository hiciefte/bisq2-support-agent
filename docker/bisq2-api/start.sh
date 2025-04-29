#!/bin/bash

# Exit on error
set -e

echo "Starting Tor..."
# Run tor directly. Logs go to stdout as configured in Dockerfile.
# Run as root initially, tor daemon might switch user internally if configured.
tor -f /etc/tor/torrc &
TOR_PID=$!

echo "Waiting for Tor to initialize on port 9050..."
# Wait until the SocksPort is listening. Requires 'ss' command (from iproute2, usually present).
# Timeout after 60 seconds.
WAIT_TIMEOUT=60
WAIT_INTERVAL=2
ELAPSED_TIME=0
while ! ss -Hltn "sport = 9050" | grep -q LISTEN; do
    if [ $ELAPSED_TIME -ge $WAIT_TIMEOUT ]; then
        echo "Tor failed to start within $WAIT_TIMEOUT seconds."
        # Optionally kill the tor process if it's hanging
        kill $TOR_PID 2>/dev/null || true
        exit 1
    fi
    sleep $WAIT_INTERVAL
    ELAPSED_TIME=$((ELAPSED_TIME + WAIT_INTERVAL))
    echo "Still waiting for Tor... (${ELAPSED_TIME}s)"
done

echo "Tor started successfully."

echo "Starting Bisq2 API Application..."
# Execute the application script created by installDist
# Pass the path to the custom config file using -Dconfig.file
# JAVA_OPTS is already set as an environment variable in the Dockerfile
# Use exec to replace the shell process with the Java process, allowing tini to manage it directly
exec /opt/bisq2/app/bin/http-api-app -Dconfig.file=/opt/bisq2/config/http_api_app.conf
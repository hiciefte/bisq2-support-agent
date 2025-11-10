#!/bin/sh
set -e

# If node_modules is empty or has very few packages, copy from build-time location
# Build installs packages to /app/node_modules during image build
# Named volume mounts over this, so we need to populate it on first run
if [ ! -d "/app/node_modules" ] || [ "$(ls -A /app/node_modules 2>/dev/null | wc -l)" -lt "50" ]; then
    echo "Initializing node_modules volume from image..."
    # Copy package.json and package-lock.json if they don't exist
    if [ ! -f "/app/package.json" ]; then
        echo "Error: package.json not found in /app"
        exit 1
    fi
    # Run npm install to populate the volume with Linux-compatible packages
    npm install --prefer-offline
    echo "node_modules initialized successfully"
fi

# Execute the main command
exec "$@"

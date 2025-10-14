#!/bin/bash
set -e

# Get the directory of the currently executing script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

echo "========================================================"
echo " Restarting Bisq Support Assistant"
echo "========================================================"

echo "--- Stopping the application ---"
"$SCRIPT_DIR/stop.sh"

echo ""
echo "--- Starting the application ---"
"$SCRIPT_DIR/start.sh"

echo "========================================================"
echo " Restart complete."
echo "========================================================"

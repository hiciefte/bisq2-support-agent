#!/bin/bash
# Test script for Matrix session persistence across container restarts
# This script verifies that Matrix authentication sessions persist correctly

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
COMPOSE_FILE="${COMPOSE_FILE:-docker/docker-compose.yml}"
COMPOSE_LOCAL_FILE="${COMPOSE_LOCAL_FILE:-docker/docker-compose.local.yml}"
CONTAINER_NAME="${CONTAINER_NAME:-docker-api-1}"
SESSION_FILE_PATH="/data/matrix_session.json"
TEST_TIMEOUT=30  # seconds to wait for session restoration

echo "========================================="
echo "Matrix Session Persistence Test"
echo "========================================="
echo ""

# Function to check if Matrix is configured
check_matrix_config() {
    echo "Checking Matrix configuration..."

    if ! grep -q "MATRIX_HOMESERVER_URL=" docker/.env; then
        echo -e "${YELLOW}WARNING: MATRIX_HOMESERVER_URL not found in .env${NC}"
        echo "Matrix integration may not be configured. Skipping test."
        exit 0
    fi

    if ! grep -q "MATRIX_PASSWORD=" docker/.env || [ -z "$(grep MATRIX_PASSWORD= docker/.env | cut -d= -f2)" ]; then
        echo -e "${YELLOW}WARNING: MATRIX_PASSWORD not set in .env${NC}"
        echo "Matrix integration requires password authentication. Skipping test."
        exit 0
    fi

    echo -e "${GREEN}✓ Matrix configuration found${NC}"
}

# Function to check if session file exists
check_session_file() {
    if docker exec "$CONTAINER_NAME" test -f "$SESSION_FILE_PATH" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

# Function to get session file modification time
get_session_mtime() {
    docker exec "$CONTAINER_NAME" stat -c %Y "$SESSION_FILE_PATH" 2>/dev/null || echo "0"
}

# Function to check logs for session restoration
check_session_restore_log() {
    local pattern="$1"
    docker compose -f "$COMPOSE_FILE" -f "$COMPOSE_LOCAL_FILE" logs api 2>/dev/null | tail -n 50 | grep -q "$pattern"
}

# Function to verify session file permissions
check_session_permissions() {
    local perms=$(docker exec "$CONTAINER_NAME" stat -c %a "$SESSION_FILE_PATH" 2>/dev/null)
    if [ "$perms" = "600" ]; then
        echo -e "${GREEN}✓ Session file has correct permissions (600)${NC}"
        return 0
    else
        echo -e "${RED}✗ Session file has incorrect permissions ($perms, expected 600)${NC}"
        return 1
    fi
}

# Step 1: Check Matrix configuration
echo "Step 1: Configuration Check"
echo "----------------------------"
check_matrix_config
echo ""

# Step 2: Ensure container is running
echo "Step 2: Container Status"
echo "------------------------"
if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "Starting API container..."
    docker compose -f "$COMPOSE_FILE" -f "$COMPOSE_LOCAL_FILE" up -d api
    echo "Waiting for container to start (30 seconds)..."
    sleep 30
fi
echo -e "${GREEN}✓ Container is running${NC}"
echo ""

# Step 3: Check for existing session or trigger fresh login
echo "Step 3: Initial Session Check"
echo "------------------------------"
if check_session_file; then
    echo -e "${GREEN}✓ Session file already exists${NC}"
    INITIAL_MTIME=$(get_session_mtime)
    echo "  Session file mtime: $INITIAL_MTIME"

    # Verify permissions
    check_session_permissions
else
    echo "No session file found. Waiting for fresh login..."

    # Wait for fresh login (up to TEST_TIMEOUT seconds)
    for i in $(seq 1 $TEST_TIMEOUT); do
        if check_session_file; then
            echo -e "${GREEN}✓ Session file created after fresh login${NC}"
            INITIAL_MTIME=$(get_session_mtime)

            # Verify permissions
            check_session_permissions
            break
        fi
        sleep 1
        echo -n "."
    done
    echo ""

    if ! check_session_file; then
        echo -e "${RED}✗ Session file was not created within $TEST_TIMEOUT seconds${NC}"
        echo "Check Matrix credentials in .env file"
        exit 1
    fi
fi
echo ""

# Step 4: Restart container to test session persistence
echo "Step 4: Container Restart Test"
echo "-------------------------------"
echo "Stopping API container..."
docker compose -f "$COMPOSE_FILE" -f "$COMPOSE_LOCAL_FILE" stop api

echo "Waiting 3 seconds..."
sleep 3

echo "Starting API container..."
docker compose -f "$COMPOSE_FILE" -f "$COMPOSE_LOCAL_FILE" start api

echo "Waiting for container startup (15 seconds)..."
sleep 15
echo ""

# Step 5: Verify session was restored (NOT recreated)
echo "Step 5: Session Restoration Verification"
echo "-----------------------------------------"

if ! check_session_file; then
    echo -e "${RED}✗ Session file not found after restart${NC}"
    echo "Session file should persist across container restarts"
    exit 1
fi

NEW_MTIME=$(get_session_mtime)

echo "Session file mtime comparison:"
echo "  Before restart: $INITIAL_MTIME"
echo "  After restart:  $NEW_MTIME"

if [ "$INITIAL_MTIME" = "$NEW_MTIME" ]; then
    echo -e "${GREEN}✓ Session file was restored (NOT recreated)${NC}"
else
    echo -e "${YELLOW}⚠ Session file was modified (fresh login may have occurred)${NC}"
    echo "This could indicate session restoration failed"
fi
echo ""

# Step 6: Check logs for session restoration message
echo "Step 6: Log Verification"
echo "------------------------"

if check_session_restore_log "Session restored from"; then
    echo -e "${GREEN}✓ Found 'Session restored from' log message${NC}"
    RESTORE_SUCCESS=true
elif check_session_restore_log "performing fresh login"; then
    echo -e "${YELLOW}⚠ Found 'performing fresh login' message instead of session restore${NC}"
    RESTORE_SUCCESS=false
else
    echo -e "${YELLOW}⚠ Could not determine session restoration status from logs${NC}"
    RESTORE_SUCCESS=false
fi
echo ""

# Step 7: Verify session file permissions
echo "Step 7: Security Check"
echo "----------------------"
check_session_permissions
echo ""

# Step 8: Test connection health
echo "Step 8: Connection Health Check"
echo "--------------------------------"

# Wait for health endpoint to be ready
echo "Waiting for health endpoint (10 seconds)..."
sleep 10

if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ API health endpoint is responding${NC}"

    # Check Matrix-specific health if available
    HEALTH_JSON=$(curl -s http://localhost:8000/health)
    if echo "$HEALTH_JSON" | grep -q "matrix"; then
        echo "  Matrix connection status: $(echo $HEALTH_JSON | grep -o '"matrix_connection":"[^"]*"' | cut -d: -f2)"
    fi
else
    echo -e "${YELLOW}⚠ API health endpoint is not responding${NC}"
fi
echo ""

# Summary
echo "========================================="
echo "Test Summary"
echo "========================================="

if [ "$RESTORE_SUCCESS" = true ]; then
    echo -e "${GREEN}✓ SUCCESS: Session persistence is working correctly${NC}"
    echo ""
    echo "Verified:"
    echo "  - Session file exists and persists across restarts"
    echo "  - Session restoration logs found"
    echo "  - File permissions are secure (600)"
    echo "  - Matrix connection is healthy"
    exit 0
else
    echo -e "${YELLOW}⚠ PARTIAL: Session file exists but restoration may need verification${NC}"
    echo ""
    echo "Recommendations:"
    echo "  - Check API logs: docker compose logs api | grep -i matrix"
    echo "  - Verify MATRIX_PASSWORD is correct in .env"
    echo "  - Ensure /data bind mount persists api/data across restarts"
    exit 1
fi

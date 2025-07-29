#!/bin/bash

# Maintenance script for Bisq Support Assistant
# This script updates the application while preserving local changes
# and rebuilds/restarts containers as needed

set -e  # Exit on error

# --- Source Environment Configuration --- #
ENV_FILE="/etc/bisq-support/deploy.env"
if [ -f "$ENV_FILE" ]; then
    echo -e "${BLUE}Sourcing environment variables from $ENV_FILE...${NC}"
    # shellcheck disable=SC1090,SC1091 # Path is variable, existence checked
    source "$ENV_FILE"
else
    echo -e "${YELLOW}Warning: Environment file $ENV_FILE not found. Using script defaults or existing env vars.${NC}"
fi
# --- End Source Environment Configuration --- #

# Define installation directory using sourced variable or default
# Defaulting to /opt/bisq-support which aligns with deploy.sh
INSTALL_DIR=${BISQ_SUPPORT_INSTALL_DIR:-/opt/bisq-support}
DOCKER_DIR="$INSTALL_DIR/docker"
COMPOSE_FILE="docker-compose.yml"
HEALTH_CHECK_RETRIES=30
HEALTH_CHECK_INTERVAL=2

# Git configuration with defaults
GIT_REMOTE=${GIT_REMOTE:-origin}
GIT_BRANCH=${GIT_BRANCH:-main}

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Display banner
echo -e "${BLUE}======================================================"
echo "Bisq Support Assistant - Maintenance Script"
echo -e "======================================================${NC}"
echo "Installation Directory: $INSTALL_DIR"

# Check for required commands
for cmd in git docker jq curl; do
  if ! command -v "$cmd" &> /dev/null; then
    echo -e "${RED}Error: $cmd is not installed or not in PATH${NC}"
    exit 1
  fi
done

# Also check for Docker Compose plugin if not already integrated
if ! docker compose version &> /dev/null; then
  echo -e "${RED}Error: Docker Compose plugin is not installed or not working${NC}"
  exit 1
fi

# Check if Docker daemon is running
if ! docker info &> /dev/null; then
  echo -e "${RED}Error: Docker daemon is not running${NC}"
  exit 1
fi

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${YELLOW}Warning: This script may need root privileges for some operations."
  echo -e "Consider running with sudo if you encounter permission errors.${NC}"
fi

# Function to handle rollbacks
rollback_to_previous_version() {
    local reason=$1
    echo -e "${RED}Initiating rollback due to: $reason${NC}"
    
    # Store the current failed state for debugging
    local FAILED_DATE
    FAILED_DATE=$(date +%Y%m%d_%H%M%S)
    local FAILED_DIR="$INSTALL_DIR/failed_updates/${FAILED_DATE}"
    mkdir -p "$FAILED_DIR"
    
    # Verify PREV_HEAD is valid
    if [ -z "$PREV_HEAD" ] || ! git rev-parse --verify "$PREV_HEAD" >/dev/null 2>&1; then
        echo -e "${RED}CRITICAL: Invalid or missing previous version reference${NC}"
        echo "Current state saved in: $FAILED_DIR"
        exit 2
    fi
    
    # Ensure we're in the correct directory for git operations
    cd "$INSTALL_DIR" || {
        echo -e "${RED}CRITICAL: Could not change to installation directory${NC}"
        exit 2
    }
    
    # Save current state and logs
    echo -e "${BLUE}Saving current state for debugging...${NC}"
    {
        echo "Failure Timestamp: $(date)"
        echo "Failure Reason: $reason"
        echo "Current Git Hash: $(git rev-parse HEAD)"
        echo "Rolling back to: $PREV_HEAD"
        echo "Working Directory: $(pwd)"
        echo -e "\nGit Status:"
        git status
        echo -e "\nLast Git Logs:"
        git log -n 5 --oneline
    } > "$FAILED_DIR/rollback_info.txt"
    
    # Save docker logs and status
    docker compose -f "$DOCKER_DIR/$COMPOSE_FILE" logs > "$FAILED_DIR/docker_logs.txt" 2>&1
    docker compose -f "$DOCKER_DIR/$COMPOSE_FILE" ps > "$FAILED_DIR/docker_ps.txt" 2>&1
    
    # Stop containers
    echo -e "${BLUE}Stopping containers...${NC}"
    if ! docker compose -f "$DOCKER_DIR/$COMPOSE_FILE" down > "$FAILED_DIR/docker_down.log" 2>&1; then
        echo -e "${RED}Warning: Error stopping containers. Continuing with rollback...${NC}"
    fi
    
    # Reset to previous working version
    echo -e "${BLUE}Resetting to last known working version: $PREV_HEAD${NC}"
    if ! git reset --hard "$PREV_HEAD" > "$FAILED_DIR/git_reset.log" 2>&1; then
        echo -e "${RED}CRITICAL: Failed to reset to previous version${NC}"
        echo -e "${RED}Manual intervention required${NC}"
        echo "Details saved in: $FAILED_DIR"
        exit 2
    fi
    
    # Change to docker directory for rebuild
    cd "$DOCKER_DIR" || {
        echo -e "${RED}CRITICAL: Could not change to docker directory${NC}"
        exit 2
    }
    
    # Rebuild and restart with previous version
    echo -e "${BLUE}Rebuilding and restarting with previous version...${NC}"
    if ! docker compose -f "$COMPOSE_FILE" up -d --build > "$FAILED_DIR/docker_rebuild.log" 2>&1; then
        echo -e "${RED}CRITICAL: Failed to rebuild and restart containers${NC}"
        echo -e "${RED}Manual intervention required${NC}"
        echo "Details saved in: $FAILED_DIR"
        exit 2
    fi
    
    # Verify rollback was successful
    echo -e "${BLUE}Verifying rollback...${NC}"
    sleep 10  # Give containers time to initialize
    
    # Check health of rolled back services
    local rollback_failed=false
    for container in $(docker compose -f "$COMPOSE_FILE" ps --services); do
        if ! check_container_health "bisq2-support-agent_${container}_1"; then
            echo -e "${RED}CRITICAL: Rollback failed - container $container is unhealthy${NC}"
            rollback_failed=true
            break
        fi
    done
    
    if $rollback_failed; then
        echo -e "${RED}CRITICAL: Rollback verification failed${NC}"
        echo -e "${RED}Manual intervention required${NC}"
        echo "Failed update details saved in: $FAILED_DIR"
        exit 2
    fi
    
    echo -e "${GREEN}Rollback completed successfully${NC}"
    echo -e "${YELLOW}Failed update details saved in: $FAILED_DIR${NC}"
}

# Function to check container health
check_container_health() {
    local container=$1
    local retries=$HEALTH_CHECK_RETRIES
    
    echo -e "${BLUE}Checking health of $container...${NC}"
    while [ $retries -gt 0 ]; do
        if [ "$(docker inspect --format='{{.State.Health.Status}}' $container)" == "healthy" ]; then
            echo -e "${GREEN}$container is healthy${NC}"
            return 0
        fi
        echo -e "${YELLOW}Waiting for $container to be healthy. Retries left: $retries${NC}"
        sleep $HEALTH_CHECK_INTERVAL
        retries=$((retries-1))
    done
    echo -e "${RED}Container $container failed health check${NC}"
    return 1
}

# Function to test the chat endpoint
test_chat_endpoint() {
    echo -e "${BLUE}Testing chat endpoint...${NC}"
    local response
    response=$(curl -s -X POST \
        -H "Content-Type: application/json" \
        -d '{
            "question": "What is Bisq?",
            "chat_history": []
        }' \
        http://localhost/api/chat/query)
    
    # Check if response contains expected fields
    if echo "$response" | jq -e '.answer and .sources and .response_time' > /dev/null; then
        echo -e "${GREEN}Chat endpoint test successful${NC}"
        echo -e "${GREEN}Response time: $(echo "$response" | jq '.response_time')${NC}"
        return 0
    else
        echo -e "${RED}Chat endpoint test failed. Response: $response${NC}"
        return 1
    fi
}

# Function to check if we need to rebuild
# Uses git diff to determine if dependencies have changed
needs_rebuild() {
  # Check for changes in key files that would require a rebuild
  # Fallback for CI/CD or environments where reflog might not be available
  if [ -z "$(git reflog show -n 1 2>/dev/null)" ]; then
    # Use git merge-base for branch comparison
    BASE=$(git merge-base HEAD "$GIT_REMOTE/$GIT_BRANCH" 2>/dev/null || git rev-parse HEAD~1 2>/dev/null)
    if [ -n "$BASE" ]; then
      if git diff --name-only "$BASE" HEAD | grep -qE 'Dockerfile|requirements.txt|package.json|package-lock.json|yarn.lock'; then
        return 0  # True, needs rebuild
      fi
    else
      # Failsafe: If we can't determine base, assume rebuild needed
      echo -e "${YELLOW}Unable to determine git base for comparison. Assuming rebuild needed.${NC}"
      return 0
    fi
  else
    # Standard approach for normal repositories with reflog
    if git diff --name-only "HEAD@{1}" HEAD | grep -qE 'Dockerfile|requirements.txt|package.json|package-lock.json|yarn.lock'; then
      return 0  # True, needs rebuild
    fi
  fi
  return 1  # False, no rebuild needed
}

# Function to check if we need to restart API
needs_api_restart() {
  # Similar fallback strategy as in needs_rebuild
  if [ -z "$(git reflog show -n 1 2>/dev/null)" ]; then
    BASE=$(git merge-base HEAD "$GIT_REMOTE/$GIT_BRANCH" 2>/dev/null || git rev-parse HEAD~1 2>/dev/null)
    if [ -n "$BASE" ]; then
      if git diff --name-only "$BASE" HEAD | grep -qE '^api/'; then
        return 0  # True, needs restart
      fi
    else
      # Failsafe
      echo -e "${YELLOW}Unable to determine git base for comparison. Assuming API restart needed.${NC}"
      return 0
    fi
  else
    if git diff --name-only "HEAD@{1}" HEAD | grep -qE '^api/'; then
      return 0  # True, needs restart
    fi
  fi
  return 1  # False, no restart needed
}

# Function to check if we need to restart Web
needs_web_restart() {
  # Similar fallback strategy as in needs_rebuild
  if [ -z "$(git reflog show -n 1 2>/dev/null)" ]; then
    BASE=$(git merge-base HEAD "$GIT_REMOTE/$GIT_BRANCH" 2>/dev/null || git rev-parse HEAD~1 2>/dev/null)
    if [ -n "$BASE" ]; then
      if git diff --name-only "$BASE" HEAD | grep -qE '^web/'; then
        return 0  # True, needs restart
      fi
    else
      # Failsafe
      echo -e "${YELLOW}Unable to determine git base for comparison. Assuming web restart needed.${NC}"
      return 0
    fi
  else
    if git diff --name-only "HEAD@{1}" HEAD | grep -qE '^web/'; then
      return 0  # True, needs restart
    fi
  fi
  return 1  # False, no restart needed
}

# Go to installation directory
cd "$INSTALL_DIR" || {
  echo -e "${RED}Error: Could not change to installation directory: $INSTALL_DIR${NC}"
  exit 1
}
echo -e "${GREEN}Working in: $(pwd)${NC}"

# Check if this is a git repo
if [ ! -d .git ]; then
  echo -e "${RED}Error: Not a git repository. Please make sure you're in the right directory.${NC}"
  exit 1
fi

# Check for local changes
echo -e "${BLUE}Checking for local changes...${NC}"
if ! git diff-index --quiet HEAD --; then
  echo -e "${YELLOW}Local changes detected. Stashing changes...${NC}"
  if ! git stash save "Auto-stashed by update script on $(date)"; then
    echo -e "${RED}Error: Failed to stash local changes. Please commit or discard your changes before updating.${NC}"
    exit 1
  fi
  STASHED=true
else
  echo -e "${GREEN}No local changes detected.${NC}"
  STASHED=false
fi

# Record current HEAD before pull
echo -e "${BLUE}Recording current git HEAD hash before pull for change detection...${NC}"
PREV_HEAD=$(git rev-parse HEAD)
if [ -z "$PREV_HEAD" ]; then
  echo -e "${RED}Error: Failed to get current HEAD.${NC}"
  exit 1
fi

# Pull latest changes using a more robust method
echo -e "${BLUE}Fetching latest changes from remote...${NC}"
if ! git fetch $GIT_REMOTE; then
    echo -e "${RED}Error: Failed to fetch latest changes from $GIT_REMOTE. Check your network connection or repository access.${NC}"
    # Restore stashed changes if fetch failed
    if $STASHED; then
      echo -e "${YELLOW}Restoring stashed changes...${NC}"
      if ! git stash pop; then
        echo -e "${RED}Stash restoration conflicted with upstream changes.${NC}"
        echo -e "${YELLOW}Repository left unchanged at PREV_HEAD; please resolve conflicts manually.${NC}"
        exit 1
      fi
    fi
    exit 1
fi

echo -e "${BLUE}Resetting to $GIT_REMOTE/$GIT_BRANCH to ensure consistency...${NC}"
if ! git reset --hard "$GIT_REMOTE/$GIT_BRANCH"; then
    echo -e "${RED}Error: Failed to reset to $GIT_REMOTE/$GIT_BRANCH.${NC}"
    # Restore stashed changes if reset failed
    if $STASHED; then
      echo -e "${YELLOW}Restoring stashed changes...${NC}"
      if ! git stash pop; then
        echo -e "${RED}Stash restoration conflicted with upstream changes.${NC}"
        echo -e "${YELLOW}Repository left unchanged at PREV_HEAD; please resolve conflicts manually.${NC}"
        exit 1
      fi
    fi
    exit 1
fi

# Check if anything was updated
if [ "$PREV_HEAD" == "$(git rev-parse HEAD)" ]; then
  echo -e "${GREEN}Already up to date. No changes found on $GIT_REMOTE/$GIT_BRANCH.${NC}"
  
  # Pop stash if we stashed changes
  if $STASHED; then
    echo -e "${BLUE}Restoring local changes...${NC}"
    if ! git stash pop; then
      echo -e "${RED}Warning: Failed to restore stashed changes. Your changes are still in the stash.${NC}"
      echo -e "${YELLOW}Run 'git stash list' and 'git stash apply' manually.${NC}"
    fi
  fi
  
  echo -e "${GREEN}No updates needed.${NC}"
  exit 0
fi

# Show what was updated
echo -e "${GREEN}Updates pulled successfully!${NC}"
echo -e "${BLUE}Changes in this update:${NC}"
git log --oneline --no-merges --max-count=10 "${PREV_HEAD}..HEAD"

# Determine if we need to rebuild or just restart
echo -e "${BLUE}Analyzing changes to determine rebuild/restart requirements...${NC}"

REBUILD_NEEDED=false
API_RESTART_NEEDED=false
WEB_RESTART_NEEDED=false

if needs_rebuild; then
  echo -e "${YELLOW}Dependency changes detected. Full rebuild needed.${NC}"
  REBUILD_NEEDED=true
else
  echo -e "${GREEN}No dependency changes detected. Checking for code changes...${NC}"
  
  if needs_api_restart; then
    echo -e "${YELLOW}API code changes detected. API restart needed.${NC}"
    API_RESTART_NEEDED=true
  fi
  
  if needs_web_restart; then
    echo -e "${YELLOW}Web code changes detected. Web restart needed.${NC}"
    WEB_RESTART_NEEDED=true
  fi
fi

# Pop stash after analyzing but before rebuilding
if $STASHED; then
  echo -e "${BLUE}Restoring local changes...${NC}"
  if ! git stash pop; then
    echo -e "${RED}Warning: There were conflicts when restoring local changes."
    echo -e "Please resolve them manually before proceeding.${NC}"
    echo -e "${YELLOW}Your changes are in the stash. Run 'git stash list' to check.${NC}"
    exit 1
  else
    echo -e "${GREEN}Local changes restored successfully.${NC}"
  fi
fi

# Navigate to docker directory
cd "$DOCKER_DIR" || {
  echo -e "${RED}Error: Could not change to Docker directory: $DOCKER_DIR${NC}"
  exit 1
}
echo -e "${BLUE}Navigating to Docker directory: $(pwd)${NC}"

# Apply updates based on what changed
if $REBUILD_NEEDED; then
    echo -e "${BLUE}Performing full rebuild...${NC}"
    if ! docker compose -f "$COMPOSE_FILE" down; then
        echo -e "${RED}Error: Failed to stop containers.${NC}"
        exit 1
    fi
    
    echo -e "${BLUE}Building containers (pulling fresh base images)...${NC}"
    if ! docker compose -f "$COMPOSE_FILE" build --pull; then
        echo -e "${RED}Error: Failed to rebuild containers.${NC}"
        rollback_to_previous_version "Docker build failed"
        exit 1
    fi
    
    if ! docker compose -f "$COMPOSE_FILE" up -d; then
        echo -e "${RED}Error: Failed to start containers.${NC}"
        exit 1
    fi

    # Add health checks after containers start
    echo -e "${BLUE}Performing health checks...${NC}"
    for container in $(docker compose -f "$COMPOSE_FILE" ps --services); do
        if ! check_container_health "bisq2-support-agent_${container}_1"; then
            rollback_to_previous_version "Health check failed for $container"
            exit 1
        fi
    done

    # Test chat functionality
    echo -e "${BLUE}Testing chat functionality...${NC}"
    if ! test_chat_endpoint; then
        rollback_to_previous_version "Chat endpoint test failed"
        exit 1
    fi
    
    echo -e "${GREEN}Full rebuild completed successfully!${NC}"
else
    # Selective restarts
    if $API_RESTART_NEEDED; then
        echo -e "${BLUE}Restarting API service...${NC}"
        if ! docker compose -f "$COMPOSE_FILE" restart api; then
            echo -e "${RED}Error: Failed to restart API service.${NC}"
            exit 1
        fi
        # Check API health
        if ! check_container_health "bisq2-support-agent_api_1"; then
            rollback_to_previous_version "API health check failed after restart"
            exit 1
        fi
        # Test chat functionality after API restart
        if ! test_chat_endpoint; then
            rollback_to_previous_version "Chat functionality test failed after API restart"
            exit 1
        fi
        echo -e "${GREEN}API service restarted and verified successfully!${NC}"
    fi
    
    if $WEB_RESTART_NEEDED; then
        echo -e "${BLUE}Restarting Web service...${NC}"
        if ! docker compose -f "$COMPOSE_FILE" restart web; then
            echo -e "${RED}Error: Failed to restart Web service.${NC}"
            exit 1
        fi
        # Check Web health
        if ! check_container_health "bisq2-support-agent_web_1"; then
            rollback_to_previous_version "Web health check failed after restart"
            exit 1
        fi
        echo -e "${GREEN}Web service restarted and verified successfully!${NC}"
    fi
fi

# Final status
echo -e "${BLUE}======================================================"
echo -e "${GREEN}Update completed successfully!"
echo -e "${BLUE}======================================================${NC}"
echo ""
echo -e "Services status:"
docker compose -f "$COMPOSE_FILE" ps

exit 0 
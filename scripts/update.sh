#!/bin/bash

# Maintenance script for Bisq Support Assistant
# This script updates the application while preserving local changes
# and rebuilds/restarts containers as needed

set -e  # Exit on error

# Default installation directory
INSTALL_DIR=${INSTALL_DIR:-"/opt/bisq-support"}
DOCKER_DIR="$INSTALL_DIR/docker"

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

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${YELLOW}Warning: This script may need root privileges for some operations."
  echo -e "Consider running with sudo if you encounter permission errors.${NC}"
fi

# Function to check if we need to rebuild
needs_rebuild() {
  # Check for changes in key files that would require a rebuild
  if git diff --name-only HEAD@{1} HEAD | grep -qE 'Dockerfile|requirements.txt|package.json|package-lock.json|yarn.lock'; then
    return 0  # True, needs rebuild
  else
    return 1  # False, no rebuild needed
  fi
}

# Function to check if we need to restart API
needs_api_restart() {
  # Check for changes in API code
  if git diff --name-only HEAD@{1} HEAD | grep -qE '^api/'; then
    return 0  # True, needs restart
  else
    return 1  # False, no restart needed
  fi
}

# Function to check if we need to restart Web
needs_web_restart() {
  # Check for changes in Web code
  if git diff --name-only HEAD@{1} HEAD | grep -qE '^web/'; then
    return 0  # True, needs restart
  else
    return 1  # False, no restart needed
  fi
}

# Go to installation directory
cd "$INSTALL_DIR"
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
  git stash save "Auto-stashed by update script on $(date)"
  STASHED=true
else
  echo -e "${GREEN}No local changes detected.${NC}"
  STASHED=false
fi

# Record current HEAD before pull
echo -e "${BLUE}Recording current state...${NC}"
PREV_HEAD=$(git rev-parse HEAD)

# Pull latest changes
echo -e "${BLUE}Pulling latest changes from remote...${NC}"
git pull

# Check if anything was updated
if [ "$PREV_HEAD" == "$(git rev-parse HEAD)" ]; then
  echo -e "${GREEN}Already up to date. No changes pulled.${NC}"
  
  # Pop stash if we stashed changes
  if $STASHED; then
    echo -e "${BLUE}Restoring local changes...${NC}"
    git stash pop
  fi
  
  echo -e "${GREEN}No updates needed.${NC}"
  exit 0
fi

# Show what was updated
echo -e "${GREEN}Updates pulled successfully!${NC}"
echo -e "${BLUE}Changes in this update:${NC}"
git log --oneline --no-merges ${PREV_HEAD}..HEAD

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
  if git stash pop; then
    echo -e "${GREEN}Local changes restored successfully.${NC}"
  else
    echo -e "${RED}Warning: There were conflicts when restoring local changes."
    echo -e "Please resolve them manually before proceeding.${NC}"
    exit 1
  fi
fi

# Navigate to docker directory
cd "$DOCKER_DIR"
echo -e "${BLUE}Navigating to Docker directory: $(pwd)${NC}"

# Apply updates based on what changed
if $REBUILD_NEEDED; then
  echo -e "${BLUE}Performing full rebuild...${NC}"
  docker-compose -f docker-compose.yml down
  docker-compose -f docker-compose.yml build --no-cache
  docker-compose -f docker-compose.yml up -d
  
  echo -e "${GREEN}Full rebuild completed successfully!${NC}"
else
  # Selective restarts
  if $API_RESTART_NEEDED; then
    echo -e "${BLUE}Restarting API service...${NC}"
    docker-compose -f docker-compose.yml restart api
    echo -e "${GREEN}API service restarted successfully!${NC}"
  fi
  
  if $WEB_RESTART_NEEDED; then
    echo -e "${BLUE}Restarting Web service...${NC}"
    docker-compose -f docker-compose.yml restart web
    echo -e "${GREEN}Web service restarted successfully!${NC}"
  fi
  
  if ! $API_RESTART_NEEDED && ! $WEB_RESTART_NEEDED; then
    echo -e "${GREEN}No service restarts needed.${NC}"
  fi
fi

# Final status
echo -e "${BLUE}======================================================"
echo -e "${GREEN}Update completed successfully!"
echo -e "${BLUE}======================================================${NC}"
echo ""
echo -e "Services status:"
docker-compose -f docker-compose.yml ps

exit 0 
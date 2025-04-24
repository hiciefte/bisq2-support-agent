#!/bin/bash

# Exit on error
set -e

# Configuration
REPOSITORY_URL="git@github.com:hiciefte/bisq2-support-agent.git"
INSTALL_DIR="/opt/bisq-support"
DOCKER_DIR="$INSTALL_DIR/docker"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Display banner
echo -e "${BLUE}======================================================"
echo "Bisq Support Assistant - Deployment Script"
echo "======================================================"
echo "Repository: $REPOSITORY_URL"
echo "Installation Directory: $INSTALL_DIR"
echo "------------------------------------------------------${NC}"

# Function to check if a command exists
check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}Error: $1 is not installed or not in PATH${NC}"
        exit 1
    fi
}

# Check for required commands
echo -e "${BLUE}[1/5] Checking prerequisites...${NC}"
for cmd in git docker curl; do
    check_command "$cmd"
done

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

# Install dependencies
echo -e "${BLUE}[2/5] Installing dependencies...${NC}"
sudo apt-get update
sudo apt-get install -y \
    docker.io \
    git

# Configure Docker to start on boot
echo -e "${BLUE}[3/5] Configuring Docker...${NC}"
sudo systemctl enable docker
sudo systemctl start docker

# Clone or update repository
echo -e "${BLUE}[4/5] Setting up repository...${NC}"
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}Repository already exists. Updating...${NC}"
    cd "$INSTALL_DIR"
    git fetch --all
    git reset --hard origin/main
else
    echo -e "${BLUE}Cloning repository...${NC}"
    git clone $REPOSITORY_URL "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# Setup environment
echo -e "${BLUE}[5/5] Setting up environment...${NC}"
cd "$DOCKER_DIR"
if [ ! -f .env ]; then
    cp .env.example .env
    echo -e "${YELLOW}Created new .env file from .env.example${NC}"
    echo -e "${YELLOW}Please review and update the .env file with your settings${NC}"
fi

# Update .env file with required settings
echo -e "${BLUE}Updating environment variables...${NC}"
# Prompt for OpenAI API key if not set
if ! grep -q "OPENAI_API_KEY=" .env || grep -q "OPENAI_API_KEY=$" .env; then
    read -p "Enter your OpenAI API key: " OPENAI_API_KEY
    sed -i "s/OPENAI_API_KEY=.*/OPENAI_API_KEY=$OPENAI_API_KEY/" .env
fi

# Update server IP with actual IP
SERVER_IP=$(curl -s ifconfig.me)
sed -i "s/SERVER_IP=.*/SERVER_IP=$SERVER_IP/" .env

# Create necessary directories
echo -e "${BLUE}Creating necessary directories...${NC}"
mkdir -p "$INSTALL_DIR/api/data/wiki"
mkdir -p "$INSTALL_DIR/api/data/logs"

# Start services
echo -e "${BLUE}Starting services in production mode...${NC}"
docker compose -f docker-compose.yml build --no-cache
docker compose -f docker-compose.yml up -d

# Wait for services to be healthy
echo -e "${BLUE}Waiting for services to be healthy...${NC}"
sleep 10

# Check if services are running
if ! docker compose -f docker-compose.yml ps | grep -q "Up"; then
    echo -e "${RED}Error: Some services failed to start${NC}"
    docker compose -f docker-compose.yml logs
    exit 1
fi

echo -e "${GREEN}======================================================"
echo "Deployment complete!"
echo "Your Bisq Support Assistant is running on port 3000"
echo "API is available on port 8000"
echo "Grafana dashboard is available on port 3001"
echo "Prometheus metrics are available on port 9090"
echo "======================================================"
echo -e "${YELLOW}Important:${NC}"
echo "1. Review the .env file in $DOCKER_DIR for any necessary configuration"
echo "2. The API data directory is at $INSTALL_DIR/api/data"
echo "3. Logs are available in $INSTALL_DIR/api/data/logs"
echo "4. Run './scripts/update.sh' to update the application"
echo "======================================================"${NC} 
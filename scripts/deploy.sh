#!/bin/bash

# Exit on error
set -e

# --- Source Environment Configuration --- #
ENV_FILE="/etc/bisq-support/deploy.env"
if [ -f "$ENV_FILE" ]; then
    echo "Sourcing environment variables from $ENV_FILE..."
    # shellcheck disable=SC1090,SC1091
    source "$ENV_FILE"
fi
# --- End Source Environment Configuration --- #

# Define installation directory, user, and other constants
INSTALL_DIR=${BISQ_SUPPORT_INSTALL_DIR:-/opt/bisq-support}
DOCKER_DIR="$INSTALL_DIR/docker"
COMPOSE_FILE="docker-compose.yml"
APP_USER="bisq-support"
APP_GROUP="bisq-support"
APP_UID=1001
APP_GID=1001

# --- Create Application User and Group --- #
echo "--- Ensuring application user and group ($APP_USER:$APP_GROUP) exist... ---"
if ! getent group "$APP_GROUP" >/dev/null; then
    echo "Creating group '$APP_GROUP' with GID $APP_GID..."
    groupadd -r -g "$APP_GID" "$APP_GROUP"
else
    echo "Group '$APP_GROUP' already exists."
fi

if ! id -u "$APP_USER" >/dev/null 2>&1; then
    echo "Creating user '$APP_USER' with UID $APP_UID..."
    useradd -r -u "$APP_UID" -g "$APP_GROUP" -s /bin/false -d "$INSTALL_DIR" "$APP_USER"
else
    echo "User '$APP_USER' already exists."
fi
# --- End User and Group Creation --- #

# Security Notice
echo "SECURITY NOTICE: This script contains deployment configuration for the Bisq 2 Support Agent."

echo "======================================================"
echo "Bisq Support Assistant - Deployment Script"
echo "======================================================"
echo "Installation Directory: $INSTALL_DIR"

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
echo "SSH Key Path: $SSH_KEY_PATH"
echo "------------------------------------------------------${NC}"

# Function to check if a command exists
check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${YELLOW}Warning: $1 is not installed or not in PATH${NC}"
        return 1
    fi
    return 0
}

# Check for required commands
echo -e "${BLUE}[1/6] Checking prerequisites...${NC}"

# Check for git
if ! check_command "git"; then
    echo -e "${BLUE}Installing git...${NC}"
    apt-get update
    apt-get install -y git
fi

# Check for Docker
if ! check_command "docker"; then
    echo -e "${BLUE}Installing Docker...${NC}"
    apt-get update
    apt-get install -y apt-transport-https ca-certificates curl software-properties-common
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
    add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io
    systemctl start docker
    systemctl enable docker
fi

# Check for Docker Compose plugin
if ! docker compose version &> /dev/null; then
    echo -e "${BLUE}Installing Docker Compose plugin...${NC}"
    apt-get update
    apt-get install -y docker-compose-plugin
fi

# Check for curl
if ! check_command "curl"; then
    echo -e "${BLUE}Installing curl...${NC}"
    apt-get update
    apt-get install -y curl
fi

# Check for ufw
if ! check_command "ufw"; then
    echo -e "${BLUE}Installing ufw...${NC}"
    apt-get update
    apt-get install -y ufw
fi

# Check if Docker daemon is running
if ! docker info &> /dev/null; then
    echo -e "${RED}Error: Docker daemon is not running${NC}"
    echo -e "${BLUE}Starting Docker daemon...${NC}"
    systemctl start docker
fi

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root${NC}"
    exit 1
fi

# Install dependencies
echo -e "${BLUE}[2/6] Installing dependencies...${NC}"
apt-get update
apt-get install -y \
    fail2ban \
    apparmor \
    apparmor-utils

# Configure firewall
echo -e "${BLUE}[3/6] Configuring firewall...${NC}"
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 3000/tcp  # Web frontend
ufw allow 8000/tcp  # API
ufw allow 3001/tcp  # Grafana
# Bisq2 API is not exposed to the internet, only accessible within Docker network
ufw --force enable

# Setup directories with proper permissions
echo -e "${BLUE}[4/6] Setting up directories and permissions...${NC}"
mkdir -p "$INSTALL_DIR" "$SECRETS_DIR" "$LOG_DIR"
# Set ownership for the main support agent dir and secrets/logs
chown -R bisq-support:bisq-support "$INSTALL_DIR" "$SECRETS_DIR" "$LOG_DIR"
# Set permissions
chmod 755 "$INSTALL_DIR"
chmod 700 "$SECRETS_DIR"
chmod 775 "$LOG_DIR"

# Setup SSH key for Git authentication and signing
echo -e "${BLUE}[5/6] Setting up SSH key for Git authentication and signing...${NC}"

# Check if SSH key exists, if not generate it
if [ ! -f "$SSH_KEY_PATH" ]; then
    echo -e "${YELLOW}SSH key not found at $SSH_KEY_PATH. Generating new SSH key...${NC}"

    # Ensure .ssh directory exists with proper permissions
    mkdir -p "$HOME/.ssh"
    chmod 700 "$HOME/.ssh"

    # Generate the SSH key
    ssh-keygen -t ed25519 -C "bisq2-support-agent@github.com" -f "$SSH_KEY_PATH" -N ""
    chmod 600 "$SSH_KEY_PATH"
    chmod 644 "$SSH_KEY_PATH.pub"

    echo -e "${YELLOW}SSH key generated. Please add the public key to your GitHub account:${NC}"
    echo -e "${YELLOW}1. Go to GitHub.com > Settings > SSH and GPG keys${NC}"
    echo -e "${YELLOW}2. Click 'New SSH key'${NC}"
    echo -e "${YELLOW}3. Give it a title (e.g., 'Bisq 2 Support Agent Server')${NC}"
    echo -e "${YELLOW}4. Copy and paste the following public key:${NC}"
    echo -e "${GREEN}$(cat "$SSH_KEY_PATH.pub")${NC}"
    echo -e "${YELLOW}5. Click 'Add SSH key'${NC}"
    echo -e "${YELLOW}6. Repeat steps 2-5 but select 'Signing Key' as the key type${NC}"
    echo -e "${YELLOW}Press Enter when you've added the key to GitHub...${NC}"
    read -r
else
    echo -e "${GREEN}SSH key already exists at $SSH_KEY_PATH.${NC}"
fi

# Configure Git to use the SSH key
echo -e "${BLUE}Configuring Git to use the SSH key...${NC}"
# Note: Using ssh-agent would be more secure if using passphrase-protected keys
git config --global core.sshCommand "ssh -i $SSH_KEY_PATH -o IdentitiesOnly=yes"
git config --global gpg.format ssh
git config --global user.signingkey "$SSH_KEY_PATH.pub"
git config --global commit.gpgsign true

# Test SSH connection to GitHub
echo -e "${BLUE}Testing SSH connection to GitHub...${NC}"
# Use accept-new to automatically add GitHub's key to known_hosts on first connection
if ! ssh -i "$SSH_KEY_PATH" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
    echo -e "${RED}Error: Failed to authenticate with GitHub using the SSH key${NC}"
    echo -e "${RED}Please make sure the SSH key is added to your GitHub account and allows authentication${NC}"
    exit 1
fi

# Add repository directory to Git's safe directories for the root user
git config --global --add safe.directory "$INSTALL_DIR"

# Helper function to set permissions for Support Agent directory
ensure_support_agent_perms() {
  echo -e "${BLUE}Setting ownership and permissions for $INSTALL_DIR...${NC}"
  chown -R bisq-support:bisq-support "$INSTALL_DIR"
  # Adjust permissions as needed, assuming 755 is okay for the main repo dir
  chmod 755 "$INSTALL_DIR"
}

# Clone or update support agent repository
echo -e "${BLUE}[6/6] Setting up support agent repository...${NC}"
if [ -d "$INSTALL_DIR" ] && [ -d "$INSTALL_DIR/.git" ]; then # Check for .git dir too
    echo -e "${YELLOW}Repository already exists. Updating...${NC}"
    cd "$INSTALL_DIR"
    git fetch --all
    git reset --hard origin/main # Assuming main branch for support agent
    # Set permissions after update
    ensure_support_agent_perms
else
    # If directory exists but is not a git repo, remove it first
    if [ -d "$INSTALL_DIR" ]; then
        echo -e "${YELLOW}Found existing non-repo directory at $INSTALL_DIR. Removing it...${NC}"
        rm -rf "$INSTALL_DIR"
    fi

    echo -e "${BLUE}Cloning repository...${NC}"
    # Quote URL/DIR, add --depth 1 for potential speedup
    git clone --depth 1 "$REPOSITORY_URL" -b main "$INSTALL_DIR"
    # Set permissions after clone
    ensure_support_agent_perms
fi

cd "$INSTALL_DIR" # Ensure we are in the correct directory

# Setup environment and secrets
echo -e "${BLUE}Setting up environment and secrets...${NC}"
cd "$DOCKER_DIR"

# Create secrets directory if it doesn't exist
mkdir -p "$SECRETS_DIR"

# Generate random secrets if they don't exist
if [ ! -f "$SECRETS_DIR/admin_api_key" ]; then
    openssl rand -base64 32 > "$SECRETS_DIR/admin_api_key"
    chmod 600 "$SECRETS_DIR/admin_api_key"
fi

if [ ! -f "$SECRETS_DIR/grafana_admin_password" ]; then
    openssl rand -base64 32 > "$SECRETS_DIR/grafana_admin_password"
    chmod 600 "$SECRETS_DIR/grafana_admin_password"
fi

# Function to safely update or add a variable to the .env file
update_env_var() {
    local key="$1"
    local value="$2"
    local env_file=".env"

    # Create .env if it doesn't exist
    touch "$env_file"

    if grep -q "^${key}=" "$env_file"; then
        # Variable exists, update it
        sed -i "s|^${key}=.*|${key}=${value}|" "$env_file"
    else
        # Variable doesn't exist, add it
        echo "${key}=${value}" >> "$env_file"
    fi
}

# Setup .env file
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo -e "${YELLOW}Created new .env file from .env.example${NC}"
    else
        touch .env
        echo -e "${YELLOW}Created empty .env file (missing .env.example)${NC}"
    fi
    echo -e "${YELLOW}Please review and update the .env file with your settings${NC}"
fi

# Prompt for OpenAI API key *if* not set or empty
OPENAI_API_KEY_CURRENT=$(grep "^OPENAI_API_KEY=" .env | cut -d '=' -f2-)
if [ -z "$OPENAI_API_KEY_CURRENT" ]; then
    echo -e "${YELLOW}OpenAI API key is missing or empty in .env file.${NC}"
    read -p "Enter your OpenAI API key: " OPENAI_API_KEY_INPUT
    update_env_var "OPENAI_API_KEY" "$OPENAI_API_KEY_INPUT"
else
    echo -e "${GREEN}OpenAI API key found in .env file.${NC}"
fi

# Update .env file with secrets and dynamic values (only if needed or for specific updates)
ADMIN_API_KEY=$(cat "$SECRETS_DIR/admin_api_key")
update_env_var "ADMIN_API_KEY" "$ADMIN_API_KEY"

# Set Bisq API URL in .env file using the Docker service name
# This allows containers to reach the Bisq2 API service within the Docker network
update_env_var "BISQ_API_URL" "http://bisq2-api:8090"

# Create a dedicated directory for runtime secrets if it doesn't exist
RUNTIME_SECRETS_DIR="$INSTALL_DIR/runtime_secrets"
mkdir -p "$RUNTIME_SECRETS_DIR"
chown bisq-support:bisq-support "$RUNTIME_SECRETS_DIR"
chmod 700 "$RUNTIME_SECRETS_DIR" # Secure the directory

# Sync ADMIN_API_KEY to the new runtime secrets location for Prometheus
PROMETHEUS_RUNTIME_ADMIN_KEY_PATH="$RUNTIME_SECRETS_DIR/prometheus_admin_key"
if [ -n "$ADMIN_API_KEY" ]; then # ADMIN_API_KEY is already sourced from $SECRETS_DIR/admin_api_key
    echo -n "$ADMIN_API_KEY" > "$PROMETHEUS_RUNTIME_ADMIN_KEY_PATH"
    chmod 644 "$PROMETHEUS_RUNTIME_ADMIN_KEY_PATH" # Readable by Prometheus user in container
    chown bisq-support:bisq-support "$PROMETHEUS_RUNTIME_ADMIN_KEY_PATH" # Ensure correct ownership
    echo -e "${GREEN}Synced ADMIN_API_KEY to $PROMETHEUS_RUNTIME_ADMIN_KEY_PATH for Prometheus.${NC}"
else
    echo -e "${YELLOW}Warning: ADMIN_API_KEY not found. Prometheus admin metrics may not work.${NC}"
fi

# Remove the old prometheus admin key file if it exists within the docker directory structure
OLD_PROMETHEUS_ADMIN_KEY_IN_DOCKER_DIR="$DOCKER_DIR/prometheus/admin_key"
if [ -f "$OLD_PROMETHEUS_ADMIN_KEY_IN_DOCKER_DIR" ]; then
    rm -f "$OLD_PROMETHEUS_ADMIN_KEY_IN_DOCKER_DIR"
    echo -e "${YELLOW}Removed old Prometheus admin key from $OLD_PROMETHEUS_ADMIN_KEY_IN_DOCKER_DIR.${NC}"
fi

# Create necessary directories for the support agent app
echo -e "${BLUE}Creating necessary directories...${NC}"
mkdir -p "$INSTALL_DIR/api/data/wiki"
mkdir -p "$INSTALL_DIR/api/data/logs"
mkdir -p "$INSTALL_DIR/api/data/vectorstore"
mkdir -p "$INSTALL_DIR/api/data/feedback"
# Correct permissions for data dirs needed by Docker containers
# Use numeric UID/GID to ensure container (UID 1001) can write files
# This handles cases where bisq-support user has different UID on host
chown -R $APP_UID:$APP_GID "$INSTALL_DIR/api/data"
chmod -R 775 "$INSTALL_DIR/api/data"

# Start services
echo -e "${BLUE}Starting services in production mode...${NC}"
docker compose -f docker-compose.yml build --pull --no-cache
docker compose -f docker-compose.yml up -d

# Wait for services to be healthy
echo -e "${BLUE}Waiting for Docker services to become healthy...${NC}"
MAX_WAIT=180 # Increased wait time
WAIT_INTERVAL=10 # Increased check interval
ELAPSED_TIME=0

while [ $ELAPSED_TIME -lt $MAX_WAIT ]; do
    # Get total number of services defined in the compose file
    SERVICE_NAMES=$(docker compose -f docker-compose.yml config --services)
    TOTAL_SERVICES=$(echo "$SERVICE_NAMES" | wc -l)
    HEALTHY_CONTAINERS=$(docker compose -f docker-compose.yml ps --filter health=healthy -q | wc -l) # Count healthy

    if [ "$TOTAL_SERVICES" -eq 0 ]; then
      echo -e "${YELLOW}No services defined in docker-compose.yml?${NC}"
      break
    fi

    if [ "$HEALTHY_CONTAINERS" -eq "$TOTAL_SERVICES" ]; then
        echo -e "${GREEN}All $TOTAL_SERVICES Docker services are healthy.${NC}"
        break
    fi

    RUNNING_CONTAINERS=$(docker compose -f docker-compose.yml ps --filter status=running -q | wc -l)
    echo -e "${YELLOW}Waiting for services... ($HEALTHY_CONTAINERS/$TOTAL_SERVICES healthy, $RUNNING_CONTAINERS running) [${ELAPSED_TIME}s/${MAX_WAIT}s]${NC}"
    sleep $WAIT_INTERVAL
    ELAPSED_TIME=$((ELAPSED_TIME + WAIT_INTERVAL))
done

if [ $ELAPSED_TIME -ge $MAX_WAIT ]; then
    echo -e "${RED}Error: Docker services did not become healthy within $MAX_WAIT seconds.${NC}"
    # Show status and logs for debugging
    docker compose -f docker-compose.yml ps
    echo "--- Last logs --- "
    docker compose -f docker-compose.yml logs --tail=50
    # Consider exiting: exit 1
fi

# Setup automatic security updates
echo -e "${BLUE}Setting up automatic security updates...${NC}"
apt-get install -y unattended-upgrades
cat > /etc/apt/apt.conf.d/50unattended-upgrades << EOF
Unattended-Upgrade::Allowed-Origins {
    "\${distro_id}:\${distro_codename}";
    "\${distro_id}:\${distro_codename}-security";
};
Unattended-Upgrade::Package-Blacklist {
};
EOF

cat > /etc/apt/apt.conf.d/20auto-upgrades << EOF
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

echo -e "${GREEN}======================================================"
echo "Deployment complete!"
echo "Your Bisq Support Assistant is running on port 3000"
echo "API is available on port 8000"
echo "Grafana dashboard is available on port 3001"
echo "Prometheus metrics are available internally only"
echo "Bisq 2 API is running in Docker on port 8090"
echo "======================================================"
echo -e "${YELLOW}Important:${NC}"
echo "1. Review the .env file in $DOCKER_DIR for any necessary configuration"
echo "2. The API data directory is at $INSTALL_DIR/api/data"
echo "3. Logs are available in $INSTALL_DIR/api/data/logs and via 'docker compose logs'"
echo "4. Run './scripts/update.sh' to update the application"
echo "5. Security updates are configured to run automatically"
echo "6. Bisq 2 API logs are available with: docker logs bisq2-api"
echo "======================================================"${NC}

# Define installation directory using sourced variable or default
# Defaulting to /opt/bisq-support which aligns with deploy.sh
INSTALL_DIR=${BISQ_SUPPORT_INSTALL_DIR:-/opt/bisq-support}
DOCKER_DIR="$INSTALL_DIR/docker"
COMPOSE_FILE="docker-compose.yml"
HEALTH_CHECK_RETRIES=30
HEALTH_CHECK_INTERVAL=2

# Define application user and group
APP_USER="bisq-support"
APP_GROUP="bisq-support"
# Use a standard non-privileged UID/GID
APP_UID=1001
APP_GID=1001


# Git configuration with defaults
GIT_REMOTE=${GIT_REMOTE:-origin}
GIT_BRANCH=${GIT_BRANCH:-main}

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "Consider running with sudo if you encounter permission errors.${NC}"
fi

# --- Create Application User and Group --- #
echo -e "${BLUE}Ensuring application user and group ($APP_USER:$APP_GROUP) exist...${NC}"
if ! getent group "$APP_GROUP" >/dev/null; then
    echo "Creating group '$APP_GROUP' with GID $APP_GID..."
    groupadd -r -g "$APP_GID" "$APP_GROUP"
else
    echo "Group '$APP_GROUP' already exists."
fi

if ! id -u "$APP_USER" >/dev/null 2>&1; then
    echo "Creating user '$APP_USER' with UID $APP_UID..."
    useradd -r -u "$APP_UID" -g "$APP_GROUP" -s /bin/false -d "$INSTALL_DIR" "$APP_USER"
else
    echo "User '$APP_USER' already exists."
fi
# --- End User and Group Creation --- #

# Go to installation directory
cd "$INSTALL_DIR" || {
    echo "Error: Failed to change to installation directory: $INSTALL_DIR"
    exit 1
}

echo -e "${BLUE}Creating required data directories...${NC}"
mkdir -p "$INSTALL_DIR/api/data/wiki" "$INSTALL_DIR/api/data/vectorstore" "$INSTALL_DIR/api/data/feedback" "$INSTALL_DIR/api/data/logs"
mkdir -p "$INSTALL_DIR/docker/logs/nginx"
mkdir -p "$INSTALL_DIR/runtime_secrets"
mkdir -p "$INSTALL_DIR/failed_updates"

# Set ownership of the data directories using numeric UID/GID
# This ensures correct permissions even if username doesn't match UID on host
echo "Setting ownership of data directories to UID:GID $APP_UID:$APP_GID..."
chown -R "$APP_UID:$APP_GID" "$INSTALL_DIR/api/data"
chown -R "$APP_UID:$APP_GID" "$INSTALL_DIR/docker/logs"
chown -R "$APP_UID:$APP_GID" "$INSTALL_DIR/runtime_secrets"
chown -R "$APP_UID:$APP_GID" "$INSTALL_DIR/failed_updates"

# --- Docker Operations --- #
# Navigate to docker directory
cd "$DOCKER_DIR" || {
    echo "Error: Failed to change to Docker directory: $DOCKER_DIR"
    exit 1
}

# Export UID and GID for Docker Compose build arguments
export APP_UID
export APP_GID

# Stop any existing containers before building/starting
echo -e "${BLUE}Stopping any old containers...${NC}"
docker compose -f "$COMPOSE_FILE" down

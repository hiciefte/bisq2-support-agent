#!/bin/bash

# Exit on error
set -e

# Security Notice
echo "SECURITY NOTICE: This script contains deployment configuration for the Bisq 2 Support Agent."
echo "While this script is designed to be secure, it's recommended to review it before execution."
echo "Consider using environment variables for sensitive information in production environments."
echo ""

# Configuration - Use environment variables
REPOSITORY_URL=${BISQ_SUPPORT_REPO_URL}
INSTALL_DIR=${BISQ_SUPPORT_INSTALL_DIR}
DOCKER_DIR="$INSTALL_DIR/docker"
SECRETS_DIR=${BISQ_SUPPORT_SECRETS_DIR}
LOG_DIR=${BISQ_SUPPORT_LOG_DIR}
SSH_KEY_PATH=${BISQ_SUPPORT_SSH_KEY_PATH}

# Validate required environment variables
if [ -z "$REPOSITORY_URL" ] || [ -z "$INSTALL_DIR" ]; then
    echo -e "${RED}Error: Required environment variables are not set${NC}"
    echo -e "${RED}Please set the following environment variables:${NC}"
    echo -e "${RED}  BISQ_SUPPORT_REPO_URL - URL of the Bisq Support Agent repository${NC}"
    echo -e "${RED}  BISQ_SUPPORT_INSTALL_DIR - Installation directory for Bisq Support Agent${NC}"
    echo -e "${RED}  BISQ_SUPPORT_SECRETS_DIR - Directory for secrets (optional)${NC}"
    echo -e "${RED}  BISQ_SUPPORT_LOG_DIR - Directory for logs (optional)${NC}"
    echo -e "${RED}  BISQ_SUPPORT_SSH_KEY_PATH - Path to SSH key for GitHub authentication (optional)${NC}"
    exit 1
fi

# Set default values for optional variables if not provided
SECRETS_DIR=${SECRETS_DIR:-"$INSTALL_DIR/secrets"}
LOG_DIR=${LOG_DIR:-"$INSTALL_DIR/logs"}
SSH_KEY_PATH=${SSH_KEY_PATH:-"$HOME/.ssh/bisq2_support_agent"}

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

# Create dedicated user for the application
# Using a fixed UID/GID (e.g., 1001) makes it easier to map permissions
# consistently between the host and Docker containers.
# Ensure your Dockerfiles also create and use a user with this UID/GID.
FIXED_UID=1001
FIXED_GID=1001
if ! id -u bisq-support &>/dev/null; then
    echo -e "${BLUE}Creating bisq-support group and user with UID/GID $FIXED_UID/$FIXED_GID...${NC}"
    groupadd -g $FIXED_GID bisq-support || echo "Group bisq-support already exists or error creating."
    # Use -m to create the home directory if user is created
    useradd -m -d /home/bisq-support -u $FIXED_UID -g $FIXED_GID -r -s /bin/false bisq-support
else
    echo -e "${GREEN}User bisq-support already exists.${NC}"
fi

# Ensure the home directory exists and has correct ownership
# This needs to run even if the user already existed
echo -e "${BLUE}Ensuring home directory /home/bisq-support exists and has correct permissions...${NC}"
mkdir -p /home/bisq-support
chown bisq-support:bisq-support /home/bisq-support
chmod 750 /home/bisq-support # Standard home dir permissions

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

# --- Sync ADMIN_API_KEY to Prometheus admin_key file ---
# This ensures Prometheus can scrape the /admin/metrics endpoint
PROMETHEUS_ADMIN_KEY_PATH="docker/prometheus/admin_key"
if [ -n "$ADMIN_API_KEY" ]; then
    echo -n "$ADMIN_API_KEY" > "$PROMETHEUS_ADMIN_KEY_PATH"
    chmod 600 "$PROMETHEUS_ADMIN_KEY_PATH"
    echo -e "${GREEN}Synced ADMIN_API_KEY to $PROMETHEUS_ADMIN_KEY_PATH for Prometheus.${NC}"
else
    echo -e "${YELLOW}Warning: ADMIN_API_KEY not found. Prometheus admin metrics may not work.${NC}"
fi

GRAFANA_ADMIN_PASSWORD=$(cat "$SECRETS_DIR/grafana_admin_password")
update_env_var "GRAFANA_ADMIN_PASSWORD" "$GRAFANA_ADMIN_PASSWORD"

# Update server IP with actual IP (Still useful for other potential purposes)
SERVER_IP=$(curl -s ifconfig.me || echo "unknown") # Handle curl errors
update_env_var "SERVER_IP" "$SERVER_IP"

# Set Bisq API URL in .env file using the Docker service name
# This allows containers to reach the Bisq2 API service within the Docker network
update_env_var "BISQ_API_URL" "http://bisq2-api:8090"

# Create necessary directories for the support agent app
echo -e "${BLUE}Creating necessary directories...${NC}"
mkdir -p "$INSTALL_DIR/api/data/wiki"
mkdir -p "$INSTALL_DIR/api/data/logs"
mkdir -p "$INSTALL_DIR/api/data/vectorstore"
mkdir -p "$INSTALL_DIR/api/data/feedback"
# Correct permissions for data dirs needed by Docker containers
# Ensure the user inside the Docker container (ideally UID 1001) can write here
chown -R bisq-support:bisq-support "$INSTALL_DIR/api/data"
chmod -R 775 "$INSTALL_DIR/api/data" # Group writable needed if container user is bisq-support

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
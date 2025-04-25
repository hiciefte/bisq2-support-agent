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
BISQ2_REPOSITORY_URL=${BISQ2_REPO_URL}
INSTALL_DIR=${BISQ_SUPPORT_INSTALL_DIR}
BISQ2_DIR=${BISQ2_INSTALL_DIR}
DOCKER_DIR="$INSTALL_DIR/docker"
SECRETS_DIR=${BISQ_SUPPORT_SECRETS_DIR}
LOG_DIR=${BISQ_SUPPORT_LOG_DIR}
SSH_KEY_PATH=${BISQ_SUPPORT_SSH_KEY_PATH}

# Validate required environment variables
if [ -z "$REPOSITORY_URL" ] || [ -z "$BISQ2_REPOSITORY_URL" ] || [ -z "$INSTALL_DIR" ] || [ -z "$BISQ2_DIR" ]; then
    echo -e "${RED}Error: Required environment variables are not set${NC}"
    echo -e "${RED}Please set the following environment variables:${NC}"
    echo -e "${RED}  BISQ_SUPPORT_REPO_URL - URL of the Bisq Support Agent repository${NC}"
    echo -e "${RED}  BISQ2_REPO_URL - URL of the Bisq 2 repository${NC}"
    echo -e "${RED}  BISQ_SUPPORT_INSTALL_DIR - Installation directory for Bisq Support Agent${NC}"
    echo -e "${RED}  BISQ2_INSTALL_DIR - Installation directory for Bisq 2${NC}"
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
echo "Bisq 2 Repository: $BISQ2_REPOSITORY_URL"
echo "Bisq 2 Directory: $BISQ2_DIR"
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
echo -e "${BLUE}[1/9] Checking prerequisites...${NC}"

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

# Check for Java
if ! check_command "java"; then
    echo -e "${BLUE}Installing Java 21...${NC}"
    apt-get update
    apt-get install -y openjdk-21-jdk
fi

# Check Java version
JAVA_VERSION=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}' | awk -F. '{print $1}')
if [ "$JAVA_VERSION" -lt 21 ]; then
    echo -e "${RED}Error: Java 21 or later is required. Found Java $JAVA_VERSION${NC}"
    echo -e "${BLUE}Installing Java 21...${NC}"
    apt-get update
    apt-get install -y openjdk-21-jdk
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
echo -e "${BLUE}[2/9] Installing dependencies...${NC}"
apt-get update
apt-get install -y \
    auditd \
    fail2ban \
    apparmor \
    apparmor-utils \
    tor

# Configure firewall
echo -e "${BLUE}[3/9] Configuring firewall...${NC}"
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 3000/tcp  # Web frontend
ufw allow 8000/tcp  # API
ufw allow 3001/tcp  # Grafana
ufw allow 8090/tcp  # Bisq 2 API
ufw --force enable

# Function to handle audit logging issues
handle_audit_logging() {
    echo -e "${BLUE}Configuring audit logging...${NC}"
    
    # Check if auditd is installed
    if ! command -v auditd &> /dev/null; then
        echo -e "${YELLOW}Warning: auditd is not installed. Installing...${NC}"
        apt-get update
        apt-get install -y auditd
    fi
    
    # Check auditd service status
    if ! systemctl is-active --quiet auditd; then
        echo -e "${YELLOW}Warning: auditd service is not running. Attempting to start...${NC}"
        
        # Try to start the service
        if ! systemctl start auditd; then
            echo -e "${YELLOW}Warning: Failed to start auditd. Checking logs...${NC}"
            journalctl -xe | grep auditd
            
            # Try to reset audit rules
            echo -e "${YELLOW}Attempting to reset audit rules...${NC}"
            auditctl -e 0 || true
            auditctl -e 1 || true
            
            # Try starting again
            if ! systemctl start auditd; then
                echo -e "${YELLOW}Warning: Still unable to start auditd. Temporarily disabling...${NC}"
                systemctl stop auditd
                systemctl disable auditd
                return 1
            fi
        fi
    fi
    
    # Configure audit rules
    cat > /etc/audit/rules.d/bisq-support.rules << EOF
# Monitor Docker operations
-w /var/run/docker.sock -p wa -k docker

# Monitor configuration changes
-w /opt/bisq-support/docker/.env -p wa -k config
-w /opt/bisq-support/secrets -p wa -k secrets

# Monitor system calls
-a always,exit -S mount -S umount2 -S chmod -S chown -S setxattr -S lsetxattr -S fsetxattr -S unlink -S rmdir -S rename -S link -S symlink -k filesystem
EOF
    
    # Restart auditd to apply rules
    if ! systemctl restart auditd; then
        echo -e "${YELLOW}Warning: Failed to restart auditd. Continuing without audit logging...${NC}"
        return 1
    fi
    
    echo -e "${GREEN}Audit logging configured successfully${NC}"
    return 0
}

# Configure audit logging
if ! handle_audit_logging; then
    echo -e "${YELLOW}Warning: Audit logging is not active. Some security features may be limited.${NC}"
    echo -e "${YELLOW}You can troubleshoot audit logging issues after deployment using:${NC}"
    echo -e "${YELLOW}1. sudo systemctl status auditd${NC}"
    echo -e "${YELLOW}2. sudo journalctl -xe | grep auditd${NC}"
    echo -e "${YELLOW}3. sudo auditctl -e 0 && sudo auditctl -e 1${NC}"
fi

# Setup directories with proper permissions
echo -e "${BLUE}[5/9] Setting up directories and permissions...${NC}"
mkdir -p "$INSTALL_DIR" "$SECRETS_DIR" "$LOG_DIR" "$BISQ2_DIR"
chown -R root:root "$INSTALL_DIR" "$BISQ2_DIR"
chmod 755 "$INSTALL_DIR" "$BISQ2_DIR"
chmod 700 "$SECRETS_DIR"
chmod 755 "$LOG_DIR"

# Create dedicated user for the application
if ! id -u bisq-support &>/dev/null; then
    useradd -r -s /bin/false bisq-support
fi

# Setup SSH key for Git authentication and signing
echo -e "${BLUE}[6/9] Setting up SSH key for Git authentication and signing...${NC}"

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
git config --global core.sshCommand "ssh -i $SSH_KEY_PATH"
git config --global gpg.format ssh
git config --global user.signingkey "$SSH_KEY_PATH.pub"
git config --global commit.gpgsign true

# Test SSH connection to GitHub
echo -e "${BLUE}Testing SSH connection to GitHub...${NC}"
if ! ssh -i "$SSH_KEY_PATH" -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
    echo -e "${RED}Error: Failed to authenticate with GitHub using the SSH key${NC}"
    echo -e "${RED}Please make sure the SSH key is added to your GitHub account${NC}"
    exit 1
fi

# Clone or update Bisq 2 repository
echo -e "${BLUE}[7/9] Setting up Bisq 2 API...${NC}"
if [ -d "$BISQ2_DIR" ]; then
    echo -e "${YELLOW}Bisq 2 repository already exists. Updating...${NC}"
    cd "$BISQ2_DIR"
    
    # Fetch all branches
    git fetch --all
    
    # Check if the add-support-api branch exists remotely
    if git ls-remote --heads origin add-support-api | grep -q add-support-api; then
        echo -e "${BLUE}Found add-support-api branch. Using it...${NC}"
        # Check if we're already on the branch
        if [ "$(git rev-parse --abbrev-ref HEAD)" != "add-support-api" ]; then
            # Try to switch to the branch, or create it if it doesn't exist locally
            git checkout add-support-api || git checkout -b add-support-api origin/add-support-api
        fi
        # Reset to the remote branch
        git reset --hard origin/add-support-api
    else
        echo -e "${YELLOW}add-support-api branch not found. Using main branch...${NC}"
        git checkout main || git checkout -b main origin/main
        git reset --hard origin/main
    fi
    
    # Pull with submodules
    git pull --recurse-submodules
else
    echo -e "${BLUE}Cloning Bisq 2 repository...${NC}"
    # Check if the add-support-api branch exists
    if git ls-remote --heads $BISQ2_REPOSITORY_URL add-support-api | grep -q add-support-api; then
        echo -e "${BLUE}Cloning add-support-api branch...${NC}"
        git clone --recurse-submodules $BISQ2_REPOSITORY_URL -b add-support-api "$BISQ2_DIR"
    else
        echo -e "${YELLOW}add-support-api branch not found. Cloning main branch...${NC}"
        git clone --recurse-submodules $BISQ2_REPOSITORY_URL -b main "$BISQ2_DIR"
    fi
fi

# Create systemd service for Bisq 2 API
echo -e "${BLUE}Creating Bisq 2 API service...${NC}"
cat > /etc/systemd/system/bisq2-api.service << EOF
[Unit]
Description=Bisq2 Headless API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$BISQ2_DIR
ExecStart=$BISQ2_DIR/gradlew :apps:http-api-app:run -Djava.awt.headless=true
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
# Create a specific data directory
Environment="BISQ_DATA_DIR=$BISQ2_DIR/data"
# Set API to listen on all interfaces (important for Docker access)
Environment="BISQ_API_HOST=0.0.0.0"
# Set Java memory limits
Environment="JAVA_OPTS=-Xmx1g"

[Install]
WantedBy=multi-user.target
EOF

# Enable and start Bisq 2 API service
systemctl daemon-reload
systemctl enable bisq2-api.service
systemctl start bisq2-api.service

# Clone or update support agent repository
echo -e "${BLUE}[8/9] Setting up support agent repository...${NC}"
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

# Setup environment and secrets
echo -e "${BLUE}[9/9] Setting up environment and secrets...${NC}"
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

# Setup .env file
if [ ! -f .env ]; then
    cp .env.example .env
    echo -e "${YELLOW}Created new .env file from .env.example${NC}"
    echo -e "${YELLOW}Please review and update the .env file with your settings${NC}"
fi

# Update .env file with secrets
ADMIN_API_KEY=$(cat "$SECRETS_DIR/admin_api_key")
GRAFANA_ADMIN_PASSWORD=$(cat "$SECRETS_DIR/grafana_admin_password")

sed -i "s/ADMIN_API_KEY=.*/ADMIN_API_KEY=$ADMIN_API_KEY/" .env
sed -i "s/GRAFANA_ADMIN_PASSWORD=.*/GRAFANA_ADMIN_PASSWORD=$GRAFANA_ADMIN_PASSWORD/" .env

# Set Bisq API URL in .env file
sed -i "s|BISQ_API_URL=.*|BISQ_API_URL=http://localhost:8090|" .env

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

# Set proper permissions
chown -R bisq-support:bisq-support "$INSTALL_DIR/api/data"
chmod 755 "$INSTALL_DIR/api/data"
chmod 755 "$INSTALL_DIR/api/data/wiki"
chmod 755 "$INSTALL_DIR/api/data/logs"

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
echo "Bisq 2 API is running on port 8090"
echo "======================================================"
echo -e "${YELLOW}Important:${NC}"
echo "1. Review the .env file in $DOCKER_DIR for any necessary configuration"
echo "2. The API data directory is at $INSTALL_DIR/api/data"
echo "3. Logs are available in $INSTALL_DIR/api/data/logs"
echo "4. Audit logs are available in /var/log/audit/audit.log"
echo "5. Run './scripts/update.sh' to update the application"
echo "6. Security updates are configured to run automatically"
echo "7. Bisq 2 API logs are available with: journalctl -u bisq2-api.service"
echo "======================================================"${NC} 
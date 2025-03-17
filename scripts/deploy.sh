#!/bin/bash

# Exit on error
set -e

# Configuration
REPOSITORY_URL="git@github.com:hiciefte/bisq2-support-agent.git"
DOMAIN="support.bisq.io"  # Update with your actual domain
EMAIL="admin@bisq.io"  # Update with your contact email

# This script assumes you've already created a DigitalOcean droplet with Ubuntu 22.04
# Recommended: At least 4GB RAM, 2 CPU cores

# Display banner
echo "======================================================"
echo "Bisq Support Assistant - DigitalOcean Deployment Script"
echo "======================================================"
echo "Repository: $REPOSITORY_URL"
echo "Domain: $DOMAIN"
echo "Contact: $EMAIL"
echo "------------------------------------------------------"

# Install dependencies
echo "[1/7] Installing dependencies..."
sudo apt-get update
sudo apt-get install -y \
    docker.io \
    docker-compose \
    nginx \
    certbot \
    python3-certbot-nginx \
    git

# Configure Docker to start on boot
echo "[2/7] Configuring Docker..."
sudo systemctl enable docker
sudo systemctl start docker

# Clone repository
echo "[3/7] Cloning repository..."
git clone $REPOSITORY_URL /opt/bisq-support
cd /opt/bisq-support

# Setup environment
echo "[4/7] Setting up environment..."
cd docker
cp .env.example .env

# Update .env file with required settings
echo "Updating environment variables..."
# Prompt for OpenAI API key
read -p "Enter your OpenAI API key: " OPENAI_API_KEY
sed -i "s/OPENAI_API_KEY=.*/OPENAI_API_KEY=$OPENAI_API_KEY/" .env

# Update server IP with actual IP
SERVER_IP=$(curl -s ifconfig.me)
sed -i "s/SERVER_IP=.*/SERVER_IP=$SERVER_IP/" .env
sed -i "s/CORS_ORIGINS=.*/CORS_ORIGINS=[\"http:\/\/$DOMAIN\", \"https:\/\/$DOMAIN\", \"http:\/\/$SERVER_IP\"]/" .env

# Run server setup script to prepare directories
echo "Setting up server directories..."
chmod +x ./setup-server.sh
./setup-server.sh

# Start services
echo "[5/7] Starting services in production mode..."
docker-compose -f docker-compose.yml build --no-cache
docker-compose -f docker-compose.yml up -d

# Setup NGINX
echo "[6/7] Configuring NGINX..."
cat > /etc/nginx/sites-available/bisq-support << 'EOL'
server {
    listen 80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    location /api {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    location /metrics {
        proxy_pass http://localhost:9090;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        auth_basic "Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd;
    }

    location /grafana {
        proxy_pass http://localhost:3001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
EOL

# Replace ${DOMAIN} with actual domain in the nginx config
sed -i "s/\${DOMAIN}/$DOMAIN/g" /etc/nginx/sites-available/bisq-support

# Enable the site
ln -sf /etc/nginx/sites-available/bisq-support /etc/nginx/sites-enabled/
nginx -t && systemctl restart nginx

# Setup SSL
echo "[7/7] Setting up SSL..."
certbot --nginx -d $DOMAIN --non-interactive --agree-tos -m $EMAIL

# Setup daily data update cron job
echo "Setting up data update cron job..."
(crontab -l 2>/dev/null; echo "0 0 * * * cd /opt/bisq-support && ./scripts/download_bisq2_media_wiki.py && docker compose -f docker/docker-compose.yml restart api") | crontab -

# Create a basic HTPasswd file for metrics authentication
echo "Creating authentication for metrics endpoint..."
sudo apt-get install -y apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd admin

echo "======================================================"
echo "Deployment complete!"
echo "Your Bisq Support Assistant is available at: https://$DOMAIN"
echo "Grafana dashboard: https://$DOMAIN/grafana"
echo "Prometheus metrics: https://$DOMAIN/metrics (password protected)"
echo "======================================================" 
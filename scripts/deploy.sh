#!/bin/bash

# Exit on error
set -e

# Configuration
VULTR_API_KEY=${VULTR_API_KEY:-""}
INSTANCE_PLAN="vhf-4c-8gb"  # 4 CPU, 8GB RAM
REGION="ewr"  # New Jersey
OS_ID="387"   # Ubuntu 22.04 x64

# Check requirements
if [ -z "$VULTR_API_KEY" ]; then
    echo "Error: VULTR_API_KEY environment variable is required"
    exit 1
fi

# Install dependencies
echo "Installing dependencies..."
sudo apt-get update
sudo apt-get install -y \
    docker.io \
    docker-compose \
    nginx \
    certbot \
    python3-certbot-nginx

# Clone repository
echo "Cloning repository..."
git clone https://github.com/your-repo/bisq-support-agent.git /opt/bisq-support
cd /opt/bisq-support

# Setup environment
echo "Setting up environment..."
cp .env.example .env
# Add your environment variables here

# Start services
echo "Starting services..."
docker-compose -f docker/docker-compose.prod.yml up -d

# Setup NGINX
echo "Configuring NGINX..."
cat > /etc/nginx/sites-available/bisq-support << 'EOL'
server {
    listen 80;
    server_name your-domain.com;

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
}
EOL

ln -s /etc/nginx/sites-available/bisq-support /etc/nginx/sites-enabled/
nginx -t && systemctl restart nginx

# Setup SSL
echo "Setting up SSL..."
certbot --nginx -d your-domain.com --non-interactive --agree-tos -m your-email@example.com

# Setup FAQ extractor cron job
echo "Setting up FAQ extractor cron job..."
(crontab -l 2>/dev/null; echo "0 0 * * * cd /opt/bisq-support && docker-compose -f docker/docker-compose.prod.yml run --rm faq-extractor && docker-compose -f docker/docker-compose.prod.yml restart api") | crontab -

echo "Deployment complete!" 
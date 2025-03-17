#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Print colored message
print_message() {
  echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
  echo -e "${YELLOW}[WARN]${NC} $1"
}

# Create necessary directories
print_message "Creating necessary directories..."
mkdir -p ./logs/cron
mkdir -p ./prometheus
mkdir -p ./grafana/provisioning/datasources
mkdir -p ./grafana/provisioning/dashboards
mkdir -p ./grafana/dashboards

# Configure the server IP
print_message "Please enter your server's IP address (leave empty for 'localhost'):"
read -r server_ip

if [ -z "$server_ip" ]; then
  server_ip="localhost"
  print_message "Using 'localhost' as server IP."
fi

# Update the .env file
print_message "Updating environment variables in .env file..."
sed -i "s/SERVER_IP=.*/SERVER_IP=$server_ip/" ./.env

print_message "Configuration setup complete!"
print_message "To start the services, run: docker compose up -d"
print_message ""
print_message "Once the services are up, you can access them at:"
print_message "- Frontend: http://$server_ip:3000"
print_message "- API: http://$server_ip:8000"
print_message "- Prometheus: http://$server_ip:9090"
print_message "- Grafana: http://$server_ip:3001 (admin/securepassword)"

# Make this script executable
chmod +x ./setup-server.sh 
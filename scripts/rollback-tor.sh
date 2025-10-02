#!/bin/bash
# scripts/rollback-tor.sh
# Rollback Tor integration if issues occur
# Usage: sudo ./rollback-tor.sh

set -euo pipefail

# Source library functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

# Initialize colors and environment
setup_colors
init_common_env

display_banner "Bisq Support Assistant - Tor Rollback Script"

# Check if running as root
if ! check_root; then
    log_error "This script must be run as root"
    exit 1
fi

log_warning "=== Rolling back Tor integration ==="
log_warning "This will disable Tor and restore clearnet-only mode"
echo ""
read -p "Continue with rollback? (yes/no): " -r
if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    log_info "Rollback cancelled"
    exit 0
fi

# Backup current state before rollback
BACKUP_DIR="/opt/bisq-support/tor-rollback-backup-$(date +%Y%m%d_%H%M%S)"
log_info "Creating backup of current state in $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

# Stop Tor service
log_info "[1/5] Stopping Tor service..."
if systemctl is-active --quiet tor; then
    systemctl stop tor
    log_success "Tor service stopped"
else
    log_info "Tor service was not running"
fi

if systemctl is-enabled --quiet tor 2>/dev/null; then
    systemctl disable tor
    log_success "Tor service disabled"
fi

# Backup and restore nginx configuration
log_info "[2/5] Restoring nginx configuration..."
if [ -f "$INSTALL_DIR/docker/nginx/conf.d/default.conf" ]; then
    cp "$INSTALL_DIR/docker/nginx/conf.d/default.conf" "$BACKUP_DIR/default.conf"
fi

if [ -f "$INSTALL_DIR/docker/nginx/conf.d/default.conf.pre-tor" ]; then
    cp "$INSTALL_DIR/docker/nginx/conf.d/default.conf.pre-tor" \
       "$INSTALL_DIR/docker/nginx/conf.d/default.conf"
    log_success "Nginx configuration restored from pre-Tor backup"
else
    log_warning "No pre-Tor nginx backup found, keeping current configuration"
fi

# Remove Tor-specific nginx configuration
if [ -f "$INSTALL_DIR/docker/nginx/conf.d/tor-support.conf" ]; then
    mv "$INSTALL_DIR/docker/nginx/conf.d/tor-support.conf" "$BACKUP_DIR/"
    log_success "Tor-specific nginx configuration moved to backup"
fi

# Remove Tor environment variables
log_info "[3/5] Removing Tor environment variables..."
if [ -f "$INSTALL_DIR/docker/.env" ]; then
    cp "$INSTALL_DIR/docker/.env" "$BACKUP_DIR/.env"

    # Remove TOR_ variables
    sed -i '/^TOR_/d' "$INSTALL_DIR/docker/.env"

    # Remove .onion from CORS_ORIGINS
    sed -i 's/,http:\/\/[a-z0-9]*\.onion//' "$INSTALL_DIR/docker/.env"

    log_success "Tor environment variables removed"
fi

# Restart services
log_info "[4/5] Restarting services..."
cd "$INSTALL_DIR" || exit 1

if [ -f "$INSTALL_DIR/scripts/restart.sh" ]; then
    "$INSTALL_DIR/scripts/restart.sh"
    log_success "Services restarted"
else
    # Fallback to direct docker compose restart
    cd "$INSTALL_DIR/docker" || exit 1
    docker compose -f docker-compose.yml restart
    log_success "Docker services restarted"
fi

# Verify rollback
log_info "[5/5] Verifying rollback..."
sleep 5

if systemctl is-active --quiet tor; then
    log_error "Tor service is still running!"
    exit 1
fi

if docker ps | grep -q nginx; then
    log_success "Nginx container is running"
else
    log_error "Nginx container is not running!"
    exit 1
fi

echo ""
log_success "✓ Tor integration rolled back successfully"
log_success "✓ Services restored to clearnet-only mode"
log_info "Backup of previous configuration saved to: $BACKUP_DIR"
echo ""
log_info "To re-enable Tor, run: ./scripts/setup-tor.sh"

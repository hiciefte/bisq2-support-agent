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
source_deploy_paths "/etc/bisq-support/deploy.env" || true
init_common_env

display_banner "Bisq Support Assistant - Tor Rollback Script"

validate_clearnet_tls_material() {
    local env_file="$1"
    local certificate_dir
    local certificate_filename
    local private_key_filename
    local certificate_path
    local private_key_path
    local certificate_public_key
    local private_key_public_key

    certificate_dir=$(_read_env_value "$env_file" NGINX_TLS_CERTIFICATE_DIR)
    certificate_filename=$(_read_env_value "$env_file" NGINX_TLS_CERTIFICATE_FILENAME)
    private_key_filename=$(_read_env_value "$env_file" NGINX_TLS_PRIVATE_KEY_FILENAME)

    case "$certificate_dir" in
        /*)
            ;;
        *)
            log_error "NGINX_TLS_CERTIFICATE_DIR must be an absolute directory"
            return 1
            ;;
    esac

    local filename
    for filename in "$certificate_filename" "$private_key_filename"; do
        case "$filename" in
            ""|.|..|*[!A-Za-z0-9._-]*)
                log_error "TLS filenames must be safe basenames"
                return 1
                ;;
        esac
    done

    certificate_path="$certificate_dir/$certificate_filename"
    private_key_path="$certificate_dir/$private_key_filename"

    if [ ! -d "$certificate_dir" ] || \
        [ ! -f "$certificate_path" ] || [ ! -s "$certificate_path" ] || \
        [ ! -f "$private_key_path" ] || [ ! -s "$private_key_path" ]; then
        log_error "The selected TLS certificate pair is incomplete"
        return 1
    fi

    if ! openssl x509 -in "$certificate_path" -noout >/dev/null 2>&1; then
        log_error "The selected TLS certificate is not valid X.509 material"
        return 1
    fi
    if ! openssl x509 -in "$certificate_path" -checkend 0 \
        -noout >/dev/null 2>&1; then
        log_error "The selected TLS certificate is expired"
        return 1
    fi
    if ! openssl pkey -in "$private_key_path" -passin pass: \
        -check -noout >/dev/null 2>&1; then
        log_error "The selected TLS private key is invalid or encrypted"
        return 1
    fi

    if ! certificate_public_key=$(openssl x509 -in "$certificate_path" \
        -pubkey -noout 2>/dev/null); then
        log_error "The TLS certificate public key could not be inspected"
        return 1
    fi
    if ! private_key_public_key=$(openssl pkey -in "$private_key_path" \
        -passin pass: -pubout 2>/dev/null); then
        log_error "The TLS private key public component could not be inspected"
        return 1
    fi
    if [ "$certificate_public_key" != "$private_key_public_key" ]; then
        log_error "The selected TLS certificate and private key do not match"
        return 1
    fi

    return 0
}

require_clearnet_tls_selection() {
    local env_file="$DOCKER_DIR/.env"

    if [ "${BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE:-}" != "docker-compose.tls.yml" ]; then
        log_error "Tor rollback requires an explicit clearnet TLS selection"
        log_error "Review docs/runbooks/public-access.md before changing exposure mode"
        return 1
    fi

    if ! validate_compose_override_file "$DOCKER_DIR"; then
        return 1
    fi

    if [ ! -f "$env_file" ]; then
        log_error "Application environment is unavailable; clearnet TLS cannot be validated"
        return 1
    fi

    local required_name required_value
    for required_name in \
        NGINX_HTTP_BIND_ADDRESS \
        NGINX_HTTPS_BIND_ADDRESS \
        NGINX_TLS_CERTIFICATE_DIR \
        NGINX_TLS_CERTIFICATE_FILENAME \
        NGINX_TLS_PRIVATE_KEY_FILENAME; do
        required_value=$(_read_env_value "$env_file" "$required_name")
        if [ -z "$required_value" ]; then
            log_error "${required_name} must be selected before Tor rollback"
            return 1
        fi
    done

    if ! is_env_enabled "$(_read_env_value "$env_file" NGINX_TLS_REDIRECT_HTTP)"; then
        log_error "NGINX_TLS_REDIRECT_HTTP must be enabled before Tor rollback"
        return 1
    fi
    if ! is_env_enabled "$(_read_env_value "$env_file" COOKIE_SECURE)"; then
        log_error "COOKIE_SECURE must be enabled before Tor rollback"
        return 1
    fi

    if ! check_required_commands docker openssl; then
        return 1
    fi
    if ! validate_clearnet_tls_material "$env_file"; then
        return 1
    fi

    if ! run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" config --quiet; then
        log_error "Clearnet TLS Compose configuration is invalid"
        return 1
    fi
    local nginx_config
    if ! nginx_config=$(run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" \
        run --rm --no-deps nginx nginx -T 2>&1); then
        log_error "Nginx rejected the selected clearnet TLS configuration"
        return 1
    fi
    if ! printf '%s\n' "$nginx_config" \
        | grep -Eq '^[[:space:]]*listen[[:space:]]+443[[:space:]]+ssl;'; then
        log_error "Nginx preflight did not produce the required TLS listener"
        return 1
    fi

    return 0
}

# Keep validation functions sourceable for regression tests and operator
# diagnostics without performing rollback actions.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    return 0
fi

# Check if running as root
if ! check_root; then
    log_error "This script must be run as root"
    exit 1
fi

# Exposure mode is a human decision. Validate the persisted TLS choice before
# stopping Tor or changing any production state.
if ! require_clearnet_tls_selection; then
    exit 1
fi

log_warning "=== Rolling back Tor integration ==="
log_warning "This will disable Tor and activate the reviewed clearnet TLS mode"
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
    # Fallback through the persisted Compose configuration.
    cd "$INSTALL_DIR/docker" || exit 1
    run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" restart
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
if ! run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" exec -T nginx \
    nginx -T 2>&1 | grep -q "listen 443 ssl"; then
    log_error "Nginx is running without the reviewed TLS listener"
    exit 1
fi

log_success "✓ Services restored to the reviewed clearnet TLS mode"
log_info "Backup of previous configuration saved to: $BACKUP_DIR"
echo ""
log_info "To re-enable Tor, run: ./scripts/setup-tor.sh"

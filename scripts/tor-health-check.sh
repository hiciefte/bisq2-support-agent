#!/bin/bash
# scripts/tor-health-check.sh
# Comprehensive health check for Tor hidden service
# Usage: sudo ./tor-health-check.sh

set -euo pipefail

# Source library functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

# Initialize colors and environment
setup_colors
init_common_env

display_banner "Bisq Support Agent - Tor Health Check"

# Check if running as root
if ! check_root; then
    log_error "This script must be run as root"
    exit 1
fi

# Global health counters
CHECKS_PASSED=0
CHECKS_FAILED=0
CHECKS_WARNING=0

# Severity levels
CRITICAL_FAILS=0
HIGH_FAILS=0
MEDIUM_FAILS=0

# Check Tor service status
check_tor_service() {
    log_info "[1/12] Checking Tor service status..."

    if systemctl is-active --quiet tor; then
        log_success "Tor service is running"
        ((CHECKS_PASSED++))

        # Check uptime
        local UPTIME=$(systemctl show tor --property=ActiveEnterTimestamp --value)
        log_info "Service started: $UPTIME"
    else
        log_error "CRITICAL: Tor service is not running"
        ((CHECKS_FAILED++))
        ((CRITICAL_FAILS++))
        return 1
    fi

    if systemctl is-enabled --quiet tor; then
        log_success "Tor service is enabled (will start on boot)"
        ((CHECKS_PASSED++))
    else
        log_warning "Tor service is not enabled for autostart"
        ((CHECKS_WARNING++))
        ((MEDIUM_FAILS++))
    fi
}

# Check .onion address generation
check_onion_address() {
    log_info "[2/12] Checking .onion address..."

    local HIDDEN_SERVICE_DIR="/var/lib/tor/bisq-support"

    if [ -f "${HIDDEN_SERVICE_DIR}/hostname" ]; then
        local ONION_ADDR=$(cat "${HIDDEN_SERVICE_DIR}/hostname")
        log_success ".onion address exists: ${GREEN}${ONION_ADDR}${NC}"
        ((CHECKS_PASSED++))

        # Validate .onion format (v3 addresses are 56 characters + .onion)
        if [[ ${#ONION_ADDR} -eq 62 ]] && [[ "$ONION_ADDR" =~ \.onion$ ]]; then
            log_success ".onion address format is valid (v3)"
            ((CHECKS_PASSED++))
        else
            log_error "HIGH: Invalid .onion address format"
            ((CHECKS_FAILED++))
            ((HIGH_FAILS++))
        fi
    else
        log_error "CRITICAL: .onion address file not found"
        ((CHECKS_FAILED++))
        ((CRITICAL_FAILS++))
    fi
}

# Check SOCKS proxy availability
check_socks_proxy() {
    log_info "[3/12] Checking SOCKS proxy ports..."

    # Check port 9050 (general SOCKS)
    if netstat -tuln 2>/dev/null | grep -q ":9050" || ss -tuln 2>/dev/null | grep -q ":9050"; then
        log_success "SOCKS proxy listening on port 9050"
        ((CHECKS_PASSED++))
    else
        log_error "HIGH: SOCKS proxy not accessible on port 9050"
        ((CHECKS_FAILED++))
        ((HIGH_FAILS++))
    fi

    # Check port 9052 (API isolation)
    if netstat -tuln 2>/dev/null | grep -q ":9052" || ss -tuln 2>/dev/null | grep -q ":9052"; then
        log_success "Isolated SOCKS proxy listening on port 9052"
        ((CHECKS_PASSED++))
    else
        log_warning "Isolated SOCKS proxy not accessible on port 9052"
        ((CHECKS_WARNING++))
        ((MEDIUM_FAILS++))
    fi
}

# Check control port
check_control_port() {
    log_info "[4/12] Checking Tor control port..."

    if netstat -tuln 2>/dev/null | grep -q ":9051" || ss -tuln 2>/dev/null | grep -q ":9051"; then
        log_success "Control port listening on port 9051"
        ((CHECKS_PASSED++))
    else
        log_warning "Control port not accessible on port 9051"
        ((CHECKS_WARNING++))
        ((MEDIUM_FAILS++))
    fi
}

# Check file permissions
check_permissions() {
    log_info "[5/12] Checking file permissions..."

    local HIDDEN_SERVICE_DIR="/var/lib/tor/bisq-support"

    # Check hidden service directory permissions (should be 700)
    local HS_PERMS=$(stat -c "%a" "$HIDDEN_SERVICE_DIR" 2>/dev/null || stat -f "%OLp" "$HIDDEN_SERVICE_DIR" 2>/dev/null || echo "000")
    if [ "$HS_PERMS" = "700" ]; then
        log_success "Hidden service directory permissions correct (700)"
        ((CHECKS_PASSED++))
    else
        log_error "HIGH: Incorrect permissions on hidden service directory: $HS_PERMS (should be 700)"
        ((CHECKS_FAILED++))
        ((HIGH_FAILS++))
    fi

    # Check ownership (should be debian-tor)
    local HS_OWNER=$(stat -c "%U" "$HIDDEN_SERVICE_DIR" 2>/dev/null || stat -f "%Su" "$HIDDEN_SERVICE_DIR" 2>/dev/null || echo "unknown")
    if [ "$HS_OWNER" = "debian-tor" ] || [ "$HS_OWNER" = "_tor" ]; then
        log_success "Hidden service directory owner correct ($HS_OWNER)"
        ((CHECKS_PASSED++))
    else
        log_error "HIGH: Incorrect ownership on hidden service directory: $HS_OWNER"
        ((CHECKS_FAILED++))
        ((HIGH_FAILS++))
    fi
}

# Check Tor circuit establishment
check_tor_circuits() {
    log_info "[6/12] Checking Tor circuit status..."

    # Use tor-prompt to check circuit status if available
    if command -v tor-prompt >/dev/null 2>&1; then
        local CIRCUITS=$(echo "GETINFO circuit-status" | tor-prompt 2>/dev/null | grep "BUILT" | wc -l || echo "0")
        if [ "$CIRCUITS" -gt 0 ]; then
            log_success "Active Tor circuits: $CIRCUITS"
            ((CHECKS_PASSED++))
        else
            log_warning "No active Tor circuits found"
            ((CHECKS_WARNING++))
            ((MEDIUM_FAILS++))
        fi
    else
        log_warning "tor-prompt not available, skipping circuit check"
        ((CHECKS_WARNING++))
    fi
}

# Check Tor logs for errors
check_tor_logs() {
    log_info "[7/12] Checking Tor logs..."

    # Check for critical errors in last 24 hours
    local ERRORS=$(journalctl -u tor --since "24 hours ago" 2>/dev/null | grep -i "err" | wc -l || echo "0")
    if [ "$ERRORS" -eq 0 ]; then
        log_success "No errors in Tor logs (last 24 hours)"
        ((CHECKS_PASSED++))
    else
        log_error "HIGH: Found $ERRORS errors in Tor logs (last 24 hours)"
        ((CHECKS_FAILED++))
        ((HIGH_FAILS++))

        # Show last 5 errors
        echo ""
        log_warning "Last 5 errors:"
        journalctl -u tor --since "24 hours ago" 2>/dev/null | grep -i "err" | tail -5 || true
        echo ""
    fi

    # Check for warnings
    local WARNINGS=$(journalctl -u tor --since "1 hour ago" 2>/dev/null | grep -i "warn" | wc -l || echo "0")
    if [ "$WARNINGS" -eq 0 ]; then
        log_success "No warnings in Tor logs (last hour)"
        ((CHECKS_PASSED++))
    else
        log_warning "Found $WARNINGS warnings in Tor logs (last hour)"
        ((CHECKS_WARNING++))
        ((MEDIUM_FAILS++))
    fi
}

# Check environment configuration
check_environment() {
    log_info "[8/12] Checking environment configuration..."

    local ENV_FILE="$INSTALL_DIR/docker/.env"

    if [ -f "$ENV_FILE" ]; then
        log_success "Environment file exists: $ENV_FILE"
        ((CHECKS_PASSED++))

        # Check TOR_HIDDEN_SERVICE variable
        if grep -q "^TOR_HIDDEN_SERVICE=" "$ENV_FILE"; then
            local CONFIGURED_ONION=$(grep "^TOR_HIDDEN_SERVICE=" "$ENV_FILE" | cut -d= -f2)
            log_success "TOR_HIDDEN_SERVICE configured: $CONFIGURED_ONION"
            ((CHECKS_PASSED++))

            # Verify it matches actual .onion address
            local ACTUAL_ONION=$(cat /var/lib/tor/bisq-support/hostname 2>/dev/null || echo "")
            if [ "$CONFIGURED_ONION" = "$ACTUAL_ONION" ]; then
                log_success "Configured .onion matches actual address"
                ((CHECKS_PASSED++))
            else
                log_error "MEDIUM: Configured .onion does not match actual address"
                ((CHECKS_FAILED++))
                ((MEDIUM_FAILS++))
            fi
        else
            log_warning "TOR_HIDDEN_SERVICE not configured in .env"
            ((CHECKS_WARNING++))
            ((MEDIUM_FAILS++))
        fi

        # Check TOR_SOCKS_PROXY variable
        if grep -q "^TOR_SOCKS_PROXY=" "$ENV_FILE"; then
            local SOCKS_PROXY=$(grep "^TOR_SOCKS_PROXY=" "$ENV_FILE" | cut -d= -f2)
            log_success "TOR_SOCKS_PROXY configured: $SOCKS_PROXY"
            ((CHECKS_PASSED++))
        else
            log_warning "TOR_SOCKS_PROXY not configured in .env"
            ((CHECKS_WARNING++))
            ((MEDIUM_FAILS++))
        fi
    else
        log_error "MEDIUM: Environment file not found: $ENV_FILE"
        ((CHECKS_FAILED++))
        ((MEDIUM_FAILS++))
    fi
}

# Check key backups
check_key_backups() {
    log_info "[9/12] Checking key backups..."

    local BACKUP_DIR="$INSTALL_DIR/backups/tor-keys"

    if [ -d "$BACKUP_DIR" ]; then
        local BACKUP_COUNT=$(find "$BACKUP_DIR" -type d -name "initial-keys-*" | wc -l)
        if [ "$BACKUP_COUNT" -gt 0 ]; then
            log_success "Found $BACKUP_COUNT key backup(s)"
            ((CHECKS_PASSED++))

            # Check latest backup
            local LATEST_BACKUP=$(find "$BACKUP_DIR" -type d -name "initial-keys-*" | sort -r | head -1)
            log_info "Latest backup: $(basename "$LATEST_BACKUP")"
        else
            log_warning "No key backups found in $BACKUP_DIR"
            ((CHECKS_WARNING++))
            ((MEDIUM_FAILS++))
        fi
    else
        log_warning "Backup directory does not exist: $BACKUP_DIR"
        ((CHECKS_WARNING++))
        ((MEDIUM_FAILS++))
    fi
}

# Check hidden service reachability
check_hidden_service_reachability() {
    log_info "[10/12] Checking hidden service reachability..."

    local ONION_ADDR=$(cat /var/lib/tor/bisq-support/hostname 2>/dev/null || echo "")

    if [ -n "$ONION_ADDR" ]; then
        # Try to connect via torsocks
        if command -v torsocks >/dev/null 2>&1; then
            log_info "Testing connection to http://${ONION_ADDR}/health"

            if timeout 30 torsocks curl -s -f "http://${ONION_ADDR}/health" >/dev/null 2>&1; then
                log_success "Hidden service is reachable and responding"
                ((CHECKS_PASSED++))
            else
                log_warning "Hidden service not reachable (this is normal if nginx is not configured yet)"
                ((CHECKS_WARNING++))
            fi
        else
            log_warning "torsocks not installed, skipping reachability check"
            ((CHECKS_WARNING++))
        fi
    else
        log_error "Cannot check reachability: .onion address not found"
        ((CHECKS_FAILED++))
    fi
}

# Check Tor configuration
check_tor_config() {
    log_info "[11/12] Checking Tor configuration..."

    local TOR_CONFIG="/etc/tor/torrc"

    if [ -f "$TOR_CONFIG" ]; then
        log_success "Tor configuration file exists"
        ((CHECKS_PASSED++))

        # Check critical configuration options
        local CRITICAL_OPTIONS=(
            "HiddenServiceDir /var/lib/tor/bisq-support/"
            "HiddenServicePort 80"
            "HiddenServiceVersion 3"
            "SocksPort 9050"
            "SafeLogging 1"
        )

        local MISSING_OPTIONS=0
        for option in "${CRITICAL_OPTIONS[@]}"; do
            if ! grep -q "^${option}" "$TOR_CONFIG"; then
                log_warning "Missing or incorrect: $option"
                ((MISSING_OPTIONS++))
            fi
        done

        if [ "$MISSING_OPTIONS" -eq 0 ]; then
            log_success "All critical configuration options present"
            ((CHECKS_PASSED++))
        else
            log_warning "Missing $MISSING_OPTIONS critical configuration option(s)"
            ((CHECKS_WARNING++))
            ((MEDIUM_FAILS++))
        fi
    else
        log_error "HIGH: Tor configuration file not found"
        ((CHECKS_FAILED++))
        ((HIGH_FAILS++))
    fi
}

# Check system resources
check_system_resources() {
    log_info "[12/12] Checking system resources..."

    # Check memory usage of Tor process
    local TOR_PID=$(pgrep -x tor || echo "")
    if [ -n "$TOR_PID" ]; then
        local TOR_MEM=$(ps -o rss= -p "$TOR_PID" 2>/dev/null | awk '{print int($1/1024)}' || echo "0")
        log_info "Tor memory usage: ${TOR_MEM}MB"

        if [ "$TOR_MEM" -lt 500 ]; then
            log_success "Memory usage is normal"
            ((CHECKS_PASSED++))
        else
            log_warning "High memory usage: ${TOR_MEM}MB"
            ((CHECKS_WARNING++))
        fi
    else
        log_error "Cannot determine Tor process ID"
        ((CHECKS_FAILED++))
    fi

    # Check disk space for Tor data
    local TOR_DATA_USAGE=$(du -sm /var/lib/tor 2>/dev/null | cut -f1 || echo "0")
    log_info "Tor data directory size: ${TOR_DATA_USAGE}MB"

    if [ "$TOR_DATA_USAGE" -lt 1000 ]; then
        log_success "Disk usage is normal"
        ((CHECKS_PASSED++))
    else
        log_warning "High disk usage: ${TOR_DATA_USAGE}MB"
        ((CHECKS_WARNING++))
    fi
}

# Generate health report
generate_report() {
    echo ""
    log_info "======================================================="
    log_info "               Tor Health Check Report"
    log_info "======================================================="
    echo ""

    local TOTAL_CHECKS=$((CHECKS_PASSED + CHECKS_FAILED + CHECKS_WARNING))

    log_success "Passed:   $CHECKS_PASSED"
    log_warning "Warnings: $CHECKS_WARNING"
    log_error "Failed:   $CHECKS_FAILED"
    echo ""

    log_info "Severity Breakdown:"
    if [ "$CRITICAL_FAILS" -gt 0 ]; then
        log_error "  Critical: $CRITICAL_FAILS"
    fi
    if [ "$HIGH_FAILS" -gt 0 ]; then
        log_error "  High:     $HIGH_FAILS"
    fi
    if [ "$MEDIUM_FAILS" -gt 0 ]; then
        log_warning "  Medium:   $MEDIUM_FAILS"
    fi
    echo ""

    # Overall health status
    if [ "$CRITICAL_FAILS" -gt 0 ]; then
        log_error "Overall Health: CRITICAL - Immediate action required"
        log_error "Review Tor service status and logs: journalctl -u tor"
        return 2
    elif [ "$HIGH_FAILS" -gt 0 ]; then
        log_error "Overall Health: DEGRADED - Action recommended"
        log_warning "Review failed checks and address high-priority issues"
        return 1
    elif [ "$CHECKS_FAILED" -gt 0 ] || [ "$CHECKS_WARNING" -gt 5 ]; then
        log_warning "Overall Health: WARNING - Monitor closely"
        return 0
    else
        log_success "Overall Health: HEALTHY"
        return 0
    fi
}

# Main execution
main() {
    check_tor_service
    check_onion_address
    check_socks_proxy
    check_control_port
    check_permissions
    check_tor_circuits
    check_tor_logs
    check_environment
    check_key_backups
    check_hidden_service_reachability
    check_tor_config
    check_system_resources

    generate_report
}

main "$@"

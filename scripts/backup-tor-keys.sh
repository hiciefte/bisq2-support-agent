#!/bin/bash
# scripts/backup-tor-keys.sh
# Encrypted backup of Tor hidden service keys
# Usage: sudo ./backup-tor-keys.sh [--encrypt]

set -euo pipefail

# Source library functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

# Initialize colors and environment
setup_colors
init_common_env

display_banner "Bisq Support Agent - Tor Key Backup"

# Check if running as root
if ! check_root; then
    log_error "This script must be run as root"
    exit 1
fi

# Parse arguments
ENCRYPT=false
if [ "${1:-}" = "--encrypt" ]; then
    ENCRYPT=true
    log_info "Encryption enabled for backup"
fi

# Configuration
HIDDEN_SERVICE_DIR="/var/lib/tor/bisq-support"
BACKUP_BASE_DIR="$INSTALL_DIR/backups/tor-keys"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$BACKUP_BASE_DIR/backup-${TIMESTAMP}"

# Validate hidden service directory exists
validate_hidden_service() {
    log_info "[1/6] Validating hidden service directory..."

    if [ ! -d "$HIDDEN_SERVICE_DIR" ]; then
        log_error "Hidden service directory not found: $HIDDEN_SERVICE_DIR"
        exit 1
    fi

    if [ ! -f "$HIDDEN_SERVICE_DIR/hostname" ]; then
        log_error "Hidden service hostname file not found"
        exit 1
    fi

    if [ ! -f "$HIDDEN_SERVICE_DIR/hs_ed25519_secret_key" ]; then
        log_error "Hidden service secret key not found"
        exit 1
    fi

    log_success "Hidden service directory validated"
}

# Create backup directory
create_backup_directory() {
    log_info "[2/6] Creating backup directory..."

    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"

    log_success "Backup directory created: $BACKUP_DIR"
}

# Backup keys
backup_keys() {
    log_info "[3/6] Backing up hidden service keys..."

    # Copy all files from hidden service directory
    cp -r "${HIDDEN_SERVICE_DIR}/." "$BACKUP_DIR/"

    # Set restrictive permissions
    chmod 600 "$BACKUP_DIR"/*

    log_success "Keys backed up successfully"

    # Display backed up files
    log_info "Backed up files:"
    ls -lh "$BACKUP_DIR/" | tail -n +2 | while read -r line; do
        echo "  $line"
    done
}

# Create backup manifest
create_manifest() {
    log_info "[4/6] Creating backup manifest..."

    local MANIFEST_FILE="$BACKUP_DIR/MANIFEST.txt"
    local ONION_ADDR=$(cat "$HIDDEN_SERVICE_DIR/hostname")

    cat > "$MANIFEST_FILE" << EOF
Bisq Support Agent - Tor Hidden Service Backup
================================================

Backup Timestamp: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
Hidden Service Address: ${ONION_ADDR}
Backup Location: ${BACKUP_DIR}

Files Included:
$(ls -1 "$BACKUP_DIR" | grep -v "MANIFEST.txt")

SHA256 Checksums:
$(cd "$BACKUP_DIR" && sha256sum * 2>/dev/null | grep -v "MANIFEST.txt" || true)

CRITICAL SECURITY NOTES:
========================
1. These keys represent your .onion identity
2. Loss of keys = permanent .onion address change
3. Compromise of keys = attacker can impersonate your service
4. Store backups in multiple secure, offline locations
5. Never share these keys or commit them to version control

Recovery Instructions:
======================
1. Stop Tor service: systemctl stop tor
2. Restore keys to: /var/lib/tor/bisq-support/
3. Set ownership: chown -R debian-tor:debian-tor /var/lib/tor/bisq-support/
4. Set permissions: chmod 700 /var/lib/tor/bisq-support && chmod 600 /var/lib/tor/bisq-support/*
5. Start Tor service: systemctl start tor
6. Verify .onion address matches: cat /var/lib/tor/bisq-support/hostname
EOF

    chmod 600 "$MANIFEST_FILE"
    log_success "Manifest created: $MANIFEST_FILE"
}

# Encrypt backup (optional)
encrypt_backup() {
    if [ "$ENCRYPT" = false ]; then
        log_info "[5/6] Skipping encryption (use --encrypt to enable)"
        return 0
    fi

    log_info "[5/6] Encrypting backup..."

    # Check if gpg is available
    if ! command -v gpg >/dev/null 2>&1; then
        log_error "GPG not installed. Cannot encrypt backup."
        log_warning "Install GPG: apt install gnupg"
        exit 1
    fi

    # Create encrypted archive
    local ARCHIVE_NAME="tor-keys-${TIMESTAMP}.tar.gz"
    local ENCRYPTED_ARCHIVE="${BACKUP_BASE_DIR}/${ARCHIVE_NAME}.gpg"

    cd "$BACKUP_BASE_DIR" || exit 1

    # Create tar archive
    tar -czf "$ARCHIVE_NAME" "backup-${TIMESTAMP}/"

    # Prompt for passphrase
    log_info "Enter passphrase for encryption:"
    gpg --symmetric --cipher-algo AES256 "$ARCHIVE_NAME"

    # Remove unencrypted archive
    rm -f "$ARCHIVE_NAME"

    # Calculate checksum of encrypted file
    local CHECKSUM=$(sha256sum "$ENCRYPTED_ARCHIVE" | cut -d' ' -f1)

    log_success "Encrypted backup created: $ENCRYPTED_ARCHIVE"
    log_info "SHA256: $CHECKSUM"

    # Create decryption instructions
    cat > "${ENCRYPTED_ARCHIVE}.README" << EOF
Encrypted Tor Hidden Service Key Backup
========================================

File: ${ARCHIVE_NAME}.gpg
Created: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
SHA256: ${CHECKSUM}

To decrypt and restore:
=======================

1. Decrypt the archive:
   gpg --decrypt ${ARCHIVE_NAME}.gpg > ${ARCHIVE_NAME}

2. Extract the archive:
   tar -xzf ${ARCHIVE_NAME}

3. Follow recovery instructions in backup-${TIMESTAMP}/MANIFEST.txt

Security Recommendations:
========================
- Store this encrypted backup on multiple offline media (USB drives, etc.)
- Store the passphrase separately using a password manager
- Test decryption periodically to ensure passphrase is correct
- Create new backups after any configuration changes
EOF

    log_success "Decryption instructions: ${ENCRYPTED_ARCHIVE}.README"
}

# Cleanup old backups
cleanup_old_backups() {
    log_info "[6/6] Cleaning up old backups..."

    local RETENTION_COUNT=10  # Keep last 10 backups

    # Count existing backups
    local BACKUP_COUNT=$(find "$BACKUP_BASE_DIR" -maxdepth 1 -type d -name "backup-*" | wc -l)

    if [ "$BACKUP_COUNT" -gt "$RETENTION_COUNT" ]; then
        local TO_DELETE=$((BACKUP_COUNT - RETENTION_COUNT))
        log_info "Found $BACKUP_COUNT backups, removing oldest $TO_DELETE"

        # Remove oldest backups
        find "$BACKUP_BASE_DIR" -maxdepth 1 -type d -name "backup-*" | \
            sort | head -n "$TO_DELETE" | while read -r old_backup; do
            log_warning "Removing old backup: $(basename "$old_backup")"
            rm -rf "$old_backup"
        done

        log_success "Removed $TO_DELETE old backup(s)"
    else
        log_success "No cleanup needed ($BACKUP_COUNT/$RETENTION_COUNT backups)"
    fi

    # Also cleanup old encrypted archives if encryption was used
    if [ "$ENCRYPT" = true ]; then
        local ENCRYPTED_COUNT=$(find "$BACKUP_BASE_DIR" -maxdepth 1 -type f -name "tor-keys-*.tar.gz.gpg" | wc -l)

        if [ "$ENCRYPTED_COUNT" -gt "$RETENTION_COUNT" ]; then
            local TO_DELETE=$((ENCRYPTED_COUNT - RETENTION_COUNT))
            log_info "Found $ENCRYPTED_COUNT encrypted archives, removing oldest $TO_DELETE"

            find "$BACKUP_BASE_DIR" -maxdepth 1 -type f -name "tor-keys-*.tar.gz.gpg" | \
                sort | head -n "$TO_DELETE" | while read -r old_archive; do
                log_warning "Removing old encrypted archive: $(basename "$old_archive")"
                rm -f "$old_archive"
                rm -f "${old_archive}.README"
            done

            log_success "Removed $TO_DELETE old encrypted archive(s)"
        fi
    fi
}

# Display backup summary
display_summary() {
    echo ""
    log_success "=== Backup Complete ==="
    echo ""

    local ONION_ADDR=$(cat "$HIDDEN_SERVICE_DIR/hostname")
    log_info "Hidden Service: ${GREEN}${ONION_ADDR}${NC}"

    if [ "$ENCRYPT" = true ]; then
        local ENCRYPTED_FILE=$(find "$BACKUP_BASE_DIR" -maxdepth 1 -type f -name "tor-keys-${TIMESTAMP}.tar.gz.gpg")
        log_info "Encrypted Backup: ${ENCRYPTED_FILE}"
    else
        log_info "Unencrypted Backup: ${BACKUP_DIR}"
    fi

    echo ""
    log_error "⚠ CRITICAL SECURITY REMINDERS:"
    log_warning "  1. Store backups in secure, offline locations"
    log_warning "  2. Never commit keys to version control"
    log_warning "  3. Loss of keys = permanent .onion address change"
    log_warning "  4. Test recovery procedure periodically"

    if [ "$ENCRYPT" = false ]; then
        echo ""
        log_warning "⚠ Backup is NOT encrypted!"
        log_info "   Run with --encrypt for encrypted backups"
    fi

    echo ""
    log_info "To restore from backup:"
    log_info "  1. Stop Tor: systemctl stop tor"
    log_info "  2. Restore keys to /var/lib/tor/bisq-support/"
    log_info "  3. Fix permissions: chown -R debian-tor:debian-tor /var/lib/tor/bisq-support/"
    log_info "  4. Start Tor: systemctl start tor"
}

# Main execution
main() {
    validate_hidden_service
    create_backup_directory
    backup_keys
    create_manifest
    encrypt_backup
    cleanup_old_backups
    display_summary
}

main "$@"

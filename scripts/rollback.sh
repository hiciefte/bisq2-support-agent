#!/bin/bash
set -Eeuo pipefail

# Rollback script for Bisq Support Assistant
# This script rolls back to a previous version and restarts services

# Source library functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/docker-utils.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/git-utils.sh"

# Initialize colors and environment
setup_colors
init_common_env

# Display banner
display_banner "Bisq Support Assistant - Rollback Script"

# Source environment configuration
source_env_file

echo "Installation Directory: $INSTALL_DIR"

# Parse command line arguments
BACKUP_REF=""
LIST_BACKUPS=false
SKIP_VALIDATION=false

usage() {
    echo "Usage: $0 [OPTIONS] [BACKUP_REF]"
    echo ""
    echo "Roll back to a previous version of the Bisq Support Assistant"
    echo ""
    echo "Options:"
    echo "  -l, --list            List available backup tags"
    echo "  -s, --skip-validation Skip health validation after rollback"
    echo "  -h, --help            Show this help message"
    echo ""
    echo "Arguments:"
    echo "  BACKUP_REF            Git reference to roll back to (tag, commit, or branch)"
    echo "                        If not specified, rolls back to the most recent backup tag"
    echo ""
    echo "Examples:"
    echo "  $0                    # Roll back to most recent backup"
    echo "  $0 backup-20250930    # Roll back to specific backup tag"
    echo "  $0 -l                 # List available backups"
    echo ""
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -l|--list)
            LIST_BACKUPS=true
            shift
            ;;
        -s|--skip-validation)
            SKIP_VALIDATION=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        -*)
            log_error "Unknown option: $1"
            usage
            ;;
        *)
            BACKUP_REF="$1"
            shift
            ;;
    esac
done

# Validate environment
validate_environment() {
    log_info "Validating environment..."

    # Check for required commands
    if ! check_required_commands git docker jq; then
        exit 1
    fi

    # Check Docker Compose
    if ! check_docker_compose; then
        exit 1
    fi

    # Check if Docker daemon is running
    if ! check_docker_daemon; then
        exit 1
    fi

    # Check if running as root
    if ! check_root; then
        log_warning "This script may need root privileges for some operations"
        log_warning "Consider running with sudo if you encounter permission errors"
    fi

    log_success "Environment validation complete"
}

# List available backups
list_available_backups() {
    cd "$INSTALL_DIR" || {
        log_error "Could not change to installation directory: $INSTALL_DIR"
        exit 1
    }

    if ! validate_git_repo "$INSTALL_DIR"; then
        exit 1
    fi

    log_info "Available backups (most recent first):"
    echo ""
    list_backups "$INSTALL_DIR" 20
    echo ""
    log_info "To roll back to a specific backup, run: $0 <backup-tag>"
    exit 0
}

# Perform rollback
perform_rollback() {
    local target_ref="$1"

    cd "$INSTALL_DIR" || {
        log_error "Could not change to installation directory: $INSTALL_DIR"
        exit 1
    }

    if ! validate_git_repo "$INSTALL_DIR"; then
        exit 1
    fi

    # If no reference specified, use latest backup
    if [ -z "$target_ref" ]; then
        log_info "No backup reference specified, using most recent backup..."
        target_ref=$(get_latest_backup "$INSTALL_DIR")
        if [ $? -ne 0 ]; then
            log_error "No backup tags found. Cannot perform automatic rollback."
            log_info "Use 'git tag -l' to see available tags or specify a commit hash."
            exit 1
        fi
    fi

    log_info "Rolling back to: $target_ref"

    # Confirm with user (unless automated)
    if [ -t 0 ]; then  # Check if running interactively
        echo ""
        log_warning "This will:"
        echo "  1. Stop all services"
        echo "  2. Reset code to: $target_ref"
        echo "  3. Rebuild and restart services"
        echo ""
        read -p "Continue with rollback? (y/N) " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Rollback cancelled by user"
            exit 0
        fi
    fi

    # Create backup of current state before rollback
    log_info "Creating backup of current state before rollback..."
    if ! create_backup_reference "$INSTALL_DIR" "pre-rollback-$(date +%Y%m%d_%H%M%S)"; then
        log_warning "Failed to create pre-rollback backup tag, but continuing..."
    fi

    # Stop services
    log_info "Stopping services..."
    cd "$DOCKER_DIR" || exit 1
    if ! stop_services "$DOCKER_DIR" "$COMPOSE_FILE"; then
        log_error "Failed to stop services"
        exit 1
    fi

    # Perform git rollback
    cd "$INSTALL_DIR" || exit 1
    if ! rollback_to_ref "$INSTALL_DIR" "$target_ref"; then
        log_error "Failed to rollback to $target_ref"
        log_error "Services are stopped. You may need to manually fix the issue."
        exit 1
    fi

    # Rebuild and restart services
    log_info "Rebuilding and restarting services..."
    cd "$DOCKER_DIR" || exit 1
    if ! rebuild_services "$DOCKER_DIR" "$COMPOSE_FILE"; then
        log_error "Failed to rebuild and restart services"
        log_error "You may need to manually fix the issue."
        exit 1
    fi

    log_success "Services restarted successfully"
}

# Validate rollback
validate_rollback() {
    log_info "Validating rollback..."

    cd "$DOCKER_DIR" || exit 1

    # Give services time to start
    log_info "Waiting for services to initialize..."
    sleep 15

    # Check service health
    if ! check_and_repair_services "$DOCKER_DIR" "$COMPOSE_FILE"; then
        log_error "Health check failed after rollback"
        log_error "Services may not be functioning correctly"
        return 1
    fi

    # Test chat endpoint if API is running
    log_info "Testing chat endpoint..."
    if test_chat_endpoint; then
        log_success "Chat endpoint is responding correctly"
    else
        log_warning "Chat endpoint test failed, but services are running"
        log_warning "You may need to investigate further"
    fi

    log_success "Rollback validation complete"
    return 0
}

# Main execution flow
main() {
    # Handle list backups option
    if [ "$LIST_BACKUPS" = "true" ]; then
        list_available_backups
    fi

    # Validate environment
    validate_environment

    # Perform rollback
    perform_rollback "$BACKUP_REF"

    # Validate rollback unless skipped
    if [ "$SKIP_VALIDATION" = "false" ]; then
        if ! validate_rollback; then
            log_warning "Rollback completed but validation failed"
            log_warning "Please check service logs for issues"
            exit 1
        fi
    else
        log_info "Skipping validation as requested"
    fi

    # Display final status
    log_info "======================================================"
    log_success "Rollback completed successfully!"
    log_info "======================================================"
    echo ""
    log_info "Current version:"
    cd "$INSTALL_DIR" || exit 1
    git log -1 --oneline
    echo ""
    show_service_status "$DOCKER_DIR" "$COMPOSE_FILE"
}

# Run main function
main

exit 0

#!/bin/bash
set -Eeuo pipefail

# Maintenance script for Bisq Support Assistant
# This script updates the application while preserving local changes
# and rebuilds/restarts containers as needed

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
display_banner "Bisq Support Assistant - Maintenance Script"

# Source environment configuration
source_env_file

echo "Installation Directory: $INSTALL_DIR"

# Validate environment
validate_environment() {
    log_info "Validating environment..."

    # Check for required commands
    if ! check_required_commands git docker jq curl; then
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

# Create system backup
create_system_backup() {
    log_info "Creating system backup..."

    # Change to installation directory
    cd "$INSTALL_DIR" || {
        log_error "Could not change to installation directory: $INSTALL_DIR"
        exit 1
    }

    # Validate git repository
    if ! validate_git_repo "$INSTALL_DIR"; then
        exit 1
    fi

    # Create backup tag
    if ! create_backup_reference "$INSTALL_DIR"; then
        log_warning "Failed to create backup tag, but continuing..."
    fi

    log_success "System backup created"
}

# Function to handle rollbacks with comprehensive logging
rollback_update() {
    local reason="${1:-Unknown reason}"
    log_error "Initiating rollback due to: $reason"

    # Ensure PREV_HEAD is set before attempting rollback
    if [ -z "${PREV_HEAD:-}" ]; then
        log_error "CRITICAL: PREV_HEAD not set. Cannot determine rollback target."
        log_error "This likely means update_repository was not called successfully."
        log_error "Manual intervention required to restore system state."
        exit 2
    fi

    # Store the current failed state for debugging
    local failed_date
    failed_date=$(date +%Y%m%d_%H%M%S)
    local failed_dir="$INSTALL_DIR/failed_updates/${failed_date}"
    mkdir -p "$failed_dir"

    # Change to installation directory
    cd "$INSTALL_DIR" || {
        log_error "CRITICAL: Could not change to installation directory"
        exit 2
    }

    # Save current state and logs
    log_info "Saving current state for debugging..."
    {
        echo "Failure Timestamp: $(date)"
        echo "Failure Reason: $reason"
        echo "Current Git Hash: $(git rev-parse HEAD)"
        echo "Rolling back to: $PREV_HEAD"
        echo "Working Directory: $(pwd)"
        echo -e "\nGit Status:"
        git status
        echo -e "\nLast Git Logs:"
        git log -n 5 --oneline
    } > "$failed_dir/rollback_info.txt"

    # Save docker logs and status
    cd "$DOCKER_DIR" || {
        log_error "CRITICAL: Could not change to docker directory"
        exit 2
    }

    docker compose -f "$COMPOSE_FILE" logs > "$failed_dir/docker_logs.txt" 2>&1 || true
    docker compose -f "$COMPOSE_FILE" ps > "$failed_dir/docker_ps.txt" 2>&1 || true

    # Stop containers
    log_info "Stopping containers..."
    stop_services "$DOCKER_DIR" "$COMPOSE_FILE" > "$failed_dir/docker_down.log" 2>&1 || {
        log_warning "Error stopping containers. Continuing with rollback..."
    }

    # Reset to previous working version
    cd "$INSTALL_DIR" || exit 2
    if ! rollback_to_ref "$INSTALL_DIR" "$PREV_HEAD"; then
        log_error "CRITICAL: Failed to reset to previous version"
        log_error "Manual intervention required"
        log_error "Details saved in: $failed_dir"
        exit 2
    fi

    # Rebuild and restart with previous version
    log_info "Rebuilding and restarting with previous version..."
    cd "$DOCKER_DIR" || exit 2

    if ! rebuild_services "$DOCKER_DIR" "$COMPOSE_FILE" > "$failed_dir/docker_rebuild.log" 2>&1; then
        log_error "CRITICAL: Failed to rebuild and restart containers"
        log_error "Manual intervention required"
        log_error "Details saved in: $failed_dir"
        exit 2
    fi

    # Verify rollback was successful
    log_info "Verifying rollback..."
    sleep 10  # Give containers time to initialize

    if ! check_and_repair_services "$DOCKER_DIR" "$COMPOSE_FILE"; then
        log_error "CRITICAL: Rollback verification failed"
        log_error "Manual intervention required"
        log_error "Failed update details saved in: $failed_dir"
        exit 2
    fi

    log_success "Rollback completed successfully"
    log_warning "Failed update details saved in: $failed_dir"
    exit 1
}

# Update repository
perform_update() {
    log_info "Updating repository..."

    # Change to installation directory
    cd "$INSTALL_DIR" || {
        log_error "Could not change to installation directory: $INSTALL_DIR"
        exit 1
    }

    # Update repository with stash handling
    local update_status
    update_repository "$INSTALL_DIR" "$GIT_REMOTE" "$GIT_BRANCH"
    update_status=$?

    if [ $update_status -eq 2 ]; then
        # No updates available
        log_success "No updates needed"
        exit 0
    elif [ $update_status -ne 0 ]; then
        # Update failed
        log_error "Repository update failed"
        exit 1
    fi

    log_success "Repository updated successfully"
}

# Determine update requirements
analyze_changes() {
    log_info "Analyzing changes to determine rebuild/restart requirements..."

    cd "$INSTALL_DIR" || exit 1

    REBUILD_NEEDED=false
    API_RESTART_NEEDED=false
    WEB_RESTART_NEEDED=false

    if needs_rebuild "$INSTALL_DIR"; then
        log_warning "Dependency changes detected. Full rebuild needed"
        REBUILD_NEEDED=true
    else
        log_success "No dependency changes detected. Checking for code changes..."

        if needs_api_restart "$INSTALL_DIR"; then
            log_warning "API code changes detected. API restart needed"
            API_RESTART_NEEDED=true
        fi

        if needs_web_restart "$INSTALL_DIR"; then
            log_warning "Web code changes detected. Web restart needed"
            WEB_RESTART_NEEDED=true
        fi
    fi

    export REBUILD_NEEDED
    export API_RESTART_NEEDED
    export WEB_RESTART_NEEDED
}

# Apply updates
apply_updates() {
    log_info "Applying updates..."

    cd "$DOCKER_DIR" || {
        log_error "Could not change to Docker directory: $DOCKER_DIR"
        exit 1
    }

    if [ "$REBUILD_NEEDED" = "true" ]; then
        log_info "Performing full rebuild..."

        if ! rebuild_services "$DOCKER_DIR" "$COMPOSE_FILE"; then
            rollback_update "Docker build failed"
        fi

        # Perform health checks after rebuild
        log_info "Performing health checks..."
        sleep 15  # Give services time to start

        if ! check_and_repair_services "$DOCKER_DIR" "$COMPOSE_FILE"; then
            rollback_update "Health check failed after rebuild"
        fi

        # Test chat functionality
        if ! test_chat_endpoint; then
            rollback_update "Chat endpoint test failed"
        fi

        log_success "Full rebuild completed successfully!"
    else
        # Selective restarts
        if [ "$API_RESTART_NEEDED" = "true" ]; then
            log_info "Restarting API service..."

            if ! docker compose -f "$COMPOSE_FILE" restart api; then
                log_error "Failed to restart API service"
                rollback_update "API restart failed"
            fi

            # Check API health
            sleep 10
            if ! wait_for_healthy "api" 120 "$DOCKER_DIR" "$COMPOSE_FILE"; then
                rollback_update "API health check failed after restart"
            fi

            # Test chat functionality after API restart
            if ! test_chat_endpoint; then
                rollback_update "Chat functionality test failed after API restart"
            fi

            log_success "API service restarted and verified successfully!"
        fi

        if [ "$WEB_RESTART_NEEDED" = "true" ]; then
            log_info "Restarting Web service..."

            if ! docker compose -f "$COMPOSE_FILE" restart web; then
                log_error "Failed to restart Web service"
                rollback_update "Web restart failed"
            fi

            # Check Web health
            sleep 10
            if ! wait_for_healthy "web" 60 "$DOCKER_DIR" "$COMPOSE_FILE"; then
                rollback_update "Web health check failed after restart"
            fi

            log_success "Web service restarted and verified successfully!"
        fi

        if [ "$API_RESTART_NEEDED" = "false" ] && [ "$WEB_RESTART_NEEDED" = "false" ]; then
            log_info "No service restarts needed. Configuration or non-service files changed"
        fi
    fi
}

# Fix file permissions for container access
fix_permissions() {
    log_info "Fixing container-mounted directory permissions..."

    # Use numeric UID/GID to ensure container (UID 1001) can write files
    # This handles cases where bisq-support user has different UID on host
    local APP_UID=1001
    local APP_GID=1001

    # Fix permissions for all container-mounted paths
    local paths=(
        "$INSTALL_DIR/api/data"
        "$INSTALL_DIR/docker/logs"
        "$INSTALL_DIR/runtime_secrets"
        "$INSTALL_DIR/failed_updates"
    )

    local fixed_count=0
    local skipped_count=0

    for path in "${paths[@]}"; do
        if [ -d "$path" ]; then
            chown -R "$APP_UID:$APP_GID" "$path"
            fixed_count=$((fixed_count + 1))
        else
            skipped_count=$((skipped_count + 1))
        fi
    done

    if [ "$fixed_count" -gt 0 ]; then
        log_success "Fixed permissions for $fixed_count director(ies) (UID:GID $APP_UID:$APP_GID)"
    fi

    if [ "$skipped_count" -gt 0 ]; then
        log_warning "Skipped $skipped_count non-existent director(ies)"
    fi
}

# Cleanup old backups
cleanup_backups() {
    log_info "Cleaning up old backups..."

    cd "$INSTALL_DIR" || return

    cleanup_old_backups "$INSTALL_DIR" 5
}

# Main execution flow
main() {
    # Validate environment
    validate_environment

    # Create backup before making changes
    create_system_backup

    # Update repository
    perform_update

    # Analyze what needs to be updated
    analyze_changes

    # Fix permissions before applying updates
    fix_permissions

    # Apply updates (rebuild or restart services)
    apply_updates

    # Cleanup old backups
    cleanup_backups

    # Display final status
    log_info "======================================================"
    log_success "Update completed successfully!"
    log_info "======================================================"
    echo ""
    show_service_status "$DOCKER_DIR" "$COMPOSE_FILE"
}

# Run main function
main

exit 0
#!/bin/bash
set -Eeuo pipefail

# Maintenance script for Bisq Support Assistant
# This script updates the application from a reviewed release tree and
# rebuilds/restarts containers as needed. Local source changes are rejected;
# ignored runtime data remains outside the release source boundary.

# Source library functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/docker-utils.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/git-utils.sh"

# Initialize colors and load deploy paths before deriving INSTALL_DIR.
setup_colors

if ! source_deploy_paths; then
    if [[ "${BASH_SOURCE[0]}" == "$0" && -z "${BISQ_SUPPORT_INSTALL_DIR:-}" ]]; then
        log_error "Deploy paths are unavailable; refusing to use implicit production paths"
        exit 1
    fi
fi

init_common_env

# Display banner
display_banner "Bisq Support Assistant - Maintenance Script"

echo "Installation Directory: $INSTALL_DIR"

# Validate environment
validate_environment() {
    log_info "Validating environment..."

    # Check for required commands
    if ! check_required_commands git docker jq curl openssl flock mktemp rm; then
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

    if ! pin_existing_compose_project \
        "$DOCKER_DIR" "$COMPOSE_FILE" running; then
        exit 1
    fi
    if ! persist_compose_project_name "$DOCKER_DIR"; then
        exit 1
    fi

    if ! validate_existing_api_data_identity \
        "$DOCKER_DIR" "$COMPOSE_FILE" "$INSTALL_DIR/api/data" running; then
        exit 1
    fi

    if ! validate_compose_override_file "$DOCKER_DIR"; then
        exit 1
    fi

    # Check if running as root
    if ! check_root; then
        log_warning "This script may need root privileges for some operations"
        log_warning "Consider running with sudo if you encounter permission errors"
    fi

    local grafana_secrets_dir="${BISQ_SUPPORT_SECRETS_DIR:-$INSTALL_DIR/secrets}"
    if ! ensure_grafana_runtime_secrets "$DOCKER_DIR/.env" "$grafana_secrets_dir"; then
        log_error "Grafana runtime secret provisioning failed"
        exit 1
    fi

    if ! validate_runtime_configuration "$DOCKER_DIR/.env"; then
        exit 1
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

# Function to handle rollbacks with comprehensive logging and production data preservation
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
        echo "Production Data: preserved in place outside the Git boundary"
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

    run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" logs > "$failed_dir/docker_logs.txt" 2>&1 || true
    run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" ps > "$failed_dir/docker_ps.txt" 2>&1 || true

    # Stop containers
    log_info "Stopping containers..."
    stop_services "$DOCKER_DIR" "$COMPOSE_FILE" > "$failed_dir/docker_down.log" 2>&1 || {
        log_warning "Error stopping containers. Continuing with rollback..."
    }

    # Reset only after proving the prior release cannot overwrite runtime data.
    cd "$INSTALL_DIR" || exit 2
    if ! ensure_runtime_data_git_boundary "$INSTALL_DIR" "$PREV_HEAD"; then
        log_error "CRITICAL: Prior release crosses the production data boundary"
        exit 2
    fi
    if ! rollback_to_ref "$INSTALL_DIR" "$PREV_HEAD"; then
        log_error "CRITICAL: Failed to reset to previous version"
        log_error "Manual intervention required"
        log_error "Details saved in: $failed_dir"
        exit 2
    fi

    # Recompute BUILD_ID to reflect rolled-back commit
    # This ensures /health endpoint shows correct build_id after rollback
    BUILD_ID=$(get_build_id "$INSTALL_DIR")
    export BUILD_ID
    log_info "Rollback build ID: $BUILD_ID"

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
    log_success "Production data preserved during rollback"
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

    # Release updates deliberately reject local source changes. Stashing and
    # restoring them would make the built tree differ from the evaluated commit.
    local update_status
    set +e
    update_repository "$INSTALL_DIR" "$GIT_REMOTE" "$GIT_BRANCH" false
    update_status=$?
    set -e

    if [ $update_status -eq 2 ]; then
        # No updates available
        log_success "No repository updates available"
        NO_REPO_UPDATES=true
        export NO_REPO_UPDATES
        return 0
    elif [ $update_status -ne 0 ]; then
        # Update failed
        log_error "Repository update failed"
        exit 1
    fi

    NO_REPO_UPDATES=false
    export NO_REPO_UPDATES

    log_success "Repository updated successfully"
}

verify_release_ai_quality_gate() {
    local verifier="$INSTALL_DIR/scripts/verify-release-ai-quality-gate.sh"

    log_info "Verifying the release AI-quality gate..."
    if [ ! -x "$verifier" ]; then
        log_error "Release AI-quality verifier is unavailable"
        return 1
    fi
    if ! "$verifier" \
        --repository "$INSTALL_DIR" \
        --remote "$GIT_REMOTE" \
        --env-file "$DOCKER_DIR/.env"; then
        log_error "Release AI-quality gate is missing or failed"
        return 1
    fi
    log_success "Release AI-quality gate verified"
}

# Determine update requirements
analyze_changes() {
    log_info "Analyzing changes to determine rebuild/restart requirements..."

    cd "$INSTALL_DIR" || exit 1

    REBUILD_NEEDED=false
    API_REBUILD_NEEDED=false
    WEB_REBUILD_NEEDED=false
    API_RESTART_NEEDED=false
    WEB_RESTART_NEEDED=false
    NGINX_RESTART_NEEDED=false

    # Check for dependency changes requiring full rebuild
    if needs_rebuild "$INSTALL_DIR"; then
        log_warning "Dependency changes detected. Full rebuild needed"
        REBUILD_NEEDED=true
    else
        log_success "No dependency changes detected. Checking for code changes..."

        # Check for API code changes requiring rebuild
        # CRITICAL: Production uses COPY for code, so code changes need rebuild
        if needs_api_rebuild "$INSTALL_DIR"; then
            log_warning "API code changes detected. API rebuild needed"
            API_REBUILD_NEEDED=true
        elif needs_api_restart "$INSTALL_DIR"; then
            log_warning "API config changes detected. API restart needed"
            API_RESTART_NEEDED=true
        fi

        # Check for Web code changes requiring rebuild
        # CRITICAL: Production uses COPY for code, so code changes need rebuild
        if needs_web_rebuild "$INSTALL_DIR"; then
            log_warning "Web code changes detected. Web rebuild needed"
            WEB_REBUILD_NEEDED=true
        elif needs_web_restart "$INSTALL_DIR"; then
            log_warning "Web config changes detected. Web restart needed"
            WEB_RESTART_NEEDED=true
        fi

        if needs_nginx_restart "$INSTALL_DIR"; then
            log_warning "Nginx config changes detected. Nginx restart needed"
            NGINX_RESTART_NEEDED=true
        fi
    fi

    export REBUILD_NEEDED
    export API_REBUILD_NEEDED
    export WEB_REBUILD_NEEDED
    export API_RESTART_NEEDED
    export WEB_RESTART_NEEDED
    export NGINX_RESTART_NEEDED
}

# Helper function to check if no service changes are needed
check_no_changes_needed() {
    [ "$API_REBUILD_NEEDED" = "false" ] && \
    [ "$WEB_REBUILD_NEEDED" = "false" ] && \
    [ "$API_RESTART_NEEDED" = "false" ] && \
    [ "$WEB_RESTART_NEEDED" = "false" ] && \
    [ "$NGINX_RESTART_NEEDED" = "false" ]
}

# Apply updates
apply_updates() {
    log_info "Applying updates..."

    cd "$DOCKER_DIR" || {
        log_error "Could not change to Docker directory: $DOCKER_DIR"
        exit 1
    }

    # Compute build ID for Next.js cache invalidation
    # This must be done BEFORE docker compose build
    local build_id
    build_id=$(get_build_id "$INSTALL_DIR")
    export BUILD_ID="$build_id"
    log_info "Using build ID: $BUILD_ID"

    if [ "$REBUILD_NEEDED" = "true" ]; then
        log_info "Performing full rebuild..."

        if ! rebuild_services "$DOCKER_DIR" "$COMPOSE_FILE"; then
            rollback_update "Docker build failed"
        fi

        # Perform health checks after rebuild
        log_info "Performing health checks..."
        # Wait 120s for bisq2-api start_period (longest of all services)
        # API: 60s, Web: 20s, bisq2-api: 120s, nginx: 20s
        log_info "Waiting 120 seconds for bisq2-api start_period to complete..."
        sleep 120

        if ! check_and_repair_services "$DOCKER_DIR" "$COMPOSE_FILE"; then
            rollback_update "Health check failed after rebuild"
        fi

        # Explicitly verify nginx is routing correctly before chat test
        # This ensures nginx proxy_pass to API is working after full rebuild
        log_info "Verifying nginx routing after full rebuild..."
        if ! wait_for_healthy "nginx" 60 "$DOCKER_DIR" "$COMPOSE_FILE"; then
            rollback_update "Nginx health check failed after full rebuild"
        fi

        # Reload nginx to force DNS refresh for the new API container
        # Docker's embedded DNS (127.0.0.11) may cache old container IPs
        log_info "Reloading nginx to refresh API upstream DNS..."
        if ! run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" exec -T nginx nginx -s reload; then
            log_warning "Nginx reload failed, waiting for DNS cache expiry instead..."
            sleep 15
        fi

        # Test chat functionality
        if ! test_chat_endpoint; then
            rollback_update "Chat endpoint test failed"
        fi
        if ! test_live_data_chat_endpoint; then
            rollback_update "MCP live-data smoke test failed"
        fi

        log_success "Full rebuild completed successfully!"
    else
        # Selective rebuilds or restarts
        # CRITICAL: Code changes require rebuild (production uses COPY)
        if [ "$API_REBUILD_NEEDED" = "true" ]; then
            log_info "Rebuilding API service..."

            # Build with BUILD_ID for cache invalidation, then start
            # Note: --build-arg only works with 'docker compose build', not 'up --build'
            # matrix-alert-relay consumes the API-built image and is recreated
            # with API below; it intentionally has no separate build context.
            if ! run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" build --build-arg BUILD_ID="${BUILD_ID:-bisq-support-build}" api; then
                log_error "Failed to build API service"
                rollback_update "API rebuild failed"
            fi
            if ! run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" up -d --no-deps api matrix-alert-relay; then
                log_error "Failed to start API service"
                rollback_update "API rebuild failed"
            fi

            # Check API health (wait for start_period: 90s before checking)
            sleep 95
            if ! wait_for_healthy "api" 120 "$DOCKER_DIR" "$COMPOSE_FILE"; then
                rollback_update "API health check failed after rebuild"
            fi
            if ! wait_for_healthy "matrix-alert-relay" 60 "$DOCKER_DIR" "$COMPOSE_FILE"; then
                rollback_update "Matrix alert relay health check failed after rebuild"
            fi

            # Ensure nginx is healthy and routing to the new API
            # This prevents HTTP 405 errors during chat endpoint test
            log_info "Verifying nginx routing to rebuilt API..."
            if ! wait_for_healthy "nginx" 60 "$DOCKER_DIR" "$COMPOSE_FILE"; then
                rollback_update "Nginx health check failed after API rebuild"
            fi

            # Reload nginx to force DNS refresh for the new API container
            # Docker's embedded DNS (127.0.0.11) may cache old container IPs
            log_info "Reloading nginx to refresh API upstream DNS..."
            if ! run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" exec -T nginx nginx -s reload; then
                log_warning "Nginx reload failed, waiting for DNS cache expiry instead..."
                sleep 15
            fi

            # Test chat functionality after API rebuild
            if ! test_chat_endpoint; then
                rollback_update "Chat functionality test failed after API rebuild"
            fi
            if ! test_live_data_chat_endpoint; then
                rollback_update "MCP live-data smoke test failed after API rebuild"
            fi

            log_success "API service rebuilt and verified successfully!"
        elif [ "$API_RESTART_NEEDED" = "true" ]; then
            log_info "Restarting API service..."

            if ! run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" restart api matrix-alert-relay; then
                log_error "Failed to restart API service"
                rollback_update "API restart failed"
            fi

            # Check API health (wait for start_period: 90s before checking)
            sleep 95
            if ! wait_for_healthy "api" 120 "$DOCKER_DIR" "$COMPOSE_FILE"; then
                rollback_update "API health check failed after restart"
            fi
            if ! wait_for_healthy "matrix-alert-relay" 60 "$DOCKER_DIR" "$COMPOSE_FILE"; then
                rollback_update "Matrix alert relay health check failed after restart"
            fi

            # Ensure nginx is healthy and routing to the restarted API
            # This prevents HTTP 405 errors during chat endpoint test
            log_info "Verifying nginx routing to restarted API..."
            if ! wait_for_healthy "nginx" 60 "$DOCKER_DIR" "$COMPOSE_FILE"; then
                rollback_update "Nginx health check failed after API restart"
            fi

            # Reload nginx to force DNS refresh for the restarted API container
            # Docker's embedded DNS (127.0.0.11) may cache old container IPs
            log_info "Reloading nginx to refresh API upstream DNS..."
            if ! run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" exec -T nginx nginx -s reload; then
                log_warning "Nginx reload failed, waiting for DNS cache expiry instead..."
                sleep 15
            fi

            # Test chat functionality after API restart
            if ! test_chat_endpoint; then
                rollback_update "Chat functionality test failed after API restart"
            fi
            if ! test_live_data_chat_endpoint; then
                rollback_update "MCP live-data smoke test failed after API restart"
            fi

            log_success "API service restarted and verified successfully!"
        fi

        if [ "$WEB_REBUILD_NEEDED" = "true" ]; then
            log_info "Rebuilding Web service..."

            # Build with BUILD_ID for cache invalidation, then start
            # Note: --build-arg only works with 'docker compose build', not 'up --build'
            if ! run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" build --build-arg BUILD_ID="${BUILD_ID:-bisq-support-build}" web; then
                log_error "Failed to build Web service"
                rollback_update "Web rebuild failed"
            fi
            if ! run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" up -d --no-deps web; then
                log_error "Failed to start Web service"
                rollback_update "Web rebuild failed"
            fi

            # Check Web health (wait for start_period: 20s before checking)
            sleep 20
            if ! wait_for_healthy "web" 60 "$DOCKER_DIR" "$COMPOSE_FILE"; then
                rollback_update "Web health check failed after rebuild"
            fi

            log_success "Web service rebuilt and verified successfully!"
        elif [ "$WEB_RESTART_NEEDED" = "true" ]; then
            log_info "Restarting Web service..."

            if ! run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" restart web; then
                log_error "Failed to restart Web service"
                rollback_update "Web restart failed"
            fi

            # Check Web health (wait for start_period: 20s before checking)
            sleep 20
            if ! wait_for_healthy "web" 60 "$DOCKER_DIR" "$COMPOSE_FILE"; then
                rollback_update "Web health check failed after restart"
            fi

            log_success "Web service restarted and verified successfully!"
        fi

        if [ "$NGINX_RESTART_NEEDED" = "true" ]; then
            log_info "Restarting Nginx service..."

            if ! run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" restart nginx; then
                log_error "Failed to restart Nginx service"
                rollback_update "Nginx restart failed"
            fi

            # Check Nginx health
            sleep 5
            if ! wait_for_healthy "nginx" 60 "$DOCKER_DIR" "$COMPOSE_FILE"; then
                rollback_update "Nginx health check failed after restart"
            fi

            log_success "Nginx service restarted and verified successfully!"
        fi

        # Check if no service changes are needed
        if check_no_changes_needed; then
            if [ "${NO_REPO_UPDATES:-false}" = "true" ]; then
                log_info "Repository is already current. Refreshing runtime services to apply deploy.env changes."
            else
                log_info "No service rebuilds or restarts needed. Refreshing runtime services before health verification."
            fi

            if ! refresh_runtime_services "$DOCKER_DIR" "$COMPOSE_FILE"; then
                log_error "Runtime service refresh failed"
                return 1
            fi

            if ! reconcile_runtime_services "$DOCKER_DIR" "$COMPOSE_FILE"; then
                log_error "Runtime service reconciliation failed"
                return 1
            fi
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

# Run FAQ SQLite migration if needed
# NOTE: Migration is SKIPPED if the SQLite DB already exists, even when empty.
# SQLite is the authoritative source - JSONL is only for initial migration.
# To force re-migration, manually delete faqs.db first.
run_faq_sqlite_migration() {
    log_info "Checking for FAQ SQLite migration needs..."
    local api_container_id=""

    # Check if migration script exists
    if [ ! -f "$INSTALL_DIR/api/app/scripts/migrate_to_sqlite.py" ]; then
        log_info "Migration script not found - skipping SQLite migration"
        return 0
    fi

    # Resolve the API through the pinned Compose project. A hard-coded
    # container name would silently select the wrong stack for a legacy custom
    # project name.
    if ! api_container_id=$(run_docker_compose \
        "$DOCKER_DIR" "$COMPOSE_FILE" ps --status running -q api); then
        log_error "Could not inspect the API container in the pinned Compose project"
        return 1
    fi
    if [ -z "$api_container_id" ]; then
        log_error "API container is not running; refusing to start a stale image before the candidate build"
        return 1
    fi
    if [ -z "$api_container_id" ] \
        || [[ "$api_container_id" == *$'\n'* ]] \
        || [[ ! "$api_container_id" =~ ^[0-9a-f]{12,64}$ ]]; then
        log_error "Pinned Compose project did not resolve exactly one API container"
        return 1
    fi

    # CRITICAL: Skip migration whenever SQLite already exists.
    # SQLite is the authoritative source after initial migration
    # Running migration again would overwrite verified status and lose production changes
    local faq_state
    if ! faq_state=$(docker exec "$api_container_id" python -c "
import sqlite3
from pathlib import Path
db_path = Path('/data/faqs.db')
if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    count = conn.execute('SELECT COUNT(*) FROM faqs').fetchone()[0]
    conn.close()
    print(f'existing:{count}')
else:
    print('missing')
" 2>/dev/null); then
        log_error "Could not verify the authoritative FAQ store; refusing to run migration"
        return 1
    fi

    if [ "$faq_state" != missing ] \
        && [[ ! "$faq_state" =~ ^existing:[0-9]+$ ]]; then
        log_error "FAQ store probe returned an invalid value; refusing to run migration"
        return 1
    fi

    if [[ "$faq_state" == existing:* ]]; then
        local faq_count="${faq_state#existing:}"
        log_success "SQLite already has $faq_count FAQs - skipping migration (SQLite is authoritative)"
        return 0
    fi

    log_info "SQLite DB is absent - running initial migration from JSONL..."

    # Run migration in dry-run mode first
    log_info "Running SQLite migration dry-run..."
    if docker exec "$api_container_id" python -m app.scripts.migrate_to_sqlite --dry-run 2>&1 | tee /tmp/migration_dryrun.log; then
        log_success "Dry-run completed successfully"

        # Run actual migration
        log_info "Running SQLite migration..."
        if docker exec "$api_container_id" python -m app.scripts.migrate_to_sqlite 2>&1 | tee /tmp/migration.log; then
            log_success "SQLite migration completed successfully"
            return 0
        else
            log_error "SQLite migration failed - check /tmp/migration.log for details"
            return 1
        fi
    else
        log_error "SQLite migration dry-run failed - aborting migration"
        log_info "Check /tmp/migration_dryrun.log for details"
        return 1
    fi
}

# Cleanup old backups
cleanup_backups() {
    log_info "Cleaning up old backups..."

    cd "$INSTALL_DIR" || return

    cleanup_old_backups "$INSTALL_DIR" 5
}

# Verify feedback persistence after deployment
verify_feedback_persistence() {
    log_info "Verifying feedback data persistence..."

    local verify_script="$INSTALL_DIR/scripts/verify-feedback-persistence.sh"

    if [ ! -f "$verify_script" ]; then
        log_warning "Feedback verification script not found: $verify_script"
        log_warning "Skipping feedback persistence check"
        return 0
    fi

    # Make sure script is executable
    chmod +x "$verify_script"

    # Run verification script
    if ! "$verify_script"; then
        log_warning "Feedback persistence verification failed"
        log_warning "Feedback data may not be persisting correctly"
        log_warning "Please review the output above and fix any issues"
        # Don't fail the deployment, just warn
        return 0
    fi

    log_success "Feedback persistence verified successfully"
    return 0
}

# Main execution flow
main() {
    acquire_production_lifecycle_lock "$INSTALL_DIR" || exit 1

    # Reject source changes before backups, fetches, resets, or stash handling.
    if ! ensure_release_source_tree_clean "$INSTALL_DIR"; then
        log_error "Release update requires a clean source tree"
        exit 1
    fi

    # Validate environment
    validate_environment

    # Create backup before making changes
    create_system_backup

    # Update repository
    perform_update

    # Never build or restart a commit that lacks a fresh-answer pass marker.
    if ! verify_release_ai_quality_gate; then
        if [ "${NO_REPO_UPDATES:-false}" = "true" ]; then
            exit 1
        fi
        rollback_update "Release AI-quality gate verification failed"
    fi

    # Keep every migration-like hook behind the evaluated release boundary.
    if ! run_faq_migration "$INSTALL_DIR"; then
        log_warning "FAQ migration verification had issues, but continuing deployment"
    fi

    # Analyze what needs to be updated
    analyze_changes

    # Fix permissions before applying updates
    fix_permissions

    # Run FAQ SQLite migration if migration script exists
    run_faq_sqlite_migration || {
        log_error "FAQ SQLite migration failed - rolling back update"
        rollback_update "SQLite migration failed"
    }

    # Apply updates (rebuild or restart services)
    apply_updates

    # Verify feedback persistence
    verify_feedback_persistence

    # Cleanup old backups
    cleanup_backups

    # Display final status
    log_info "======================================================"
    log_success "Update completed successfully!"
    log_info "======================================================"
    echo ""
    show_service_status "$DOCKER_DIR" "$COMPOSE_FILE"
}

# Run main function only when executed, not when sourced by tests.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main
    exit 0
fi

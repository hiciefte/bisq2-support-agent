#!/bin/bash
set -euo pipefail

# migrate-env.sh — One-time migration to single-source-of-truth env architecture
#
# Before:
#   deploy.env  → mix of path vars + app config (shadows docker/.env)
#   docker/.env → full app config (but sometimes overridden by deploy.env)
#
# After:
#   deploy.env  → ONLY deploy-path vars (repo URLs, install dirs)
#   docker/.env → ALL app config (sole source of truth for Docker Compose)
#
# This script:
#   1. Backs up both files
#   2. Merges any app config from deploy.env INTO docker/.env (deploy.env wins
#      for conflicts, since that's what was actually running)
#   3. Strips app config from deploy.env, keeping only path vars
#   4. Applies Matrix room fixes (the immediate config issue)
#
# Usage:
#   bash scripts/migrate-env.sh [--dry-run]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"
setup_colors

DEPLOY_ENV="/etc/bisq-support/deploy.env"
DOCKER_ENV="/opt/bisq-support/docker/.env"
DRY_RUN=false
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

FIX_ROOMS=true

# --- Parse args ---
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --skip-room-fix) FIX_ROOMS=false ;;
        *) log_error "Unknown argument: $arg"; exit 1 ;;
    esac
done

display_banner "Environment Migration: Single Source of Truth"

if $DRY_RUN; then
    log_warning "DRY RUN — no files will be modified"
fi

# --- Pre-flight checks ---
if [ ! -f "$DEPLOY_ENV" ]; then
    log_error "deploy.env not found at $DEPLOY_ENV"
    exit 1
fi
if [ ! -f "$DOCKER_ENV" ]; then
    log_error "docker/.env not found at $DOCKER_ENV"
    exit 1
fi

# --- Step 1: Backup ---
log_info "Step 1: Creating backups"
BACKUP_DIR="/etc/bisq-support/.backup_migrate_${TIMESTAMP}"
if ! $DRY_RUN; then
    mkdir -p "$BACKUP_DIR"
    cp "$DEPLOY_ENV" "$BACKUP_DIR/deploy.env.bak"
    cp "$DOCKER_ENV" "$BACKUP_DIR/docker.env.bak"
    log_success "Backups saved to $BACKUP_DIR/"
else
    log_info "  Would backup to $BACKUP_DIR/"
fi

# --- Step 2: Identify app config vars in deploy.env ---
log_info "Step 2: Identifying app config in deploy.env"

app_vars_in_deploy=()
while IFS= read -r line || [ -n "$line" ]; do
    # Strip whitespace and export prefix
    stripped="${line#"${line%%[![:space:]]*}"}"
    stripped="${stripped#export }"

    # Skip comments, blank lines
    [[ -z "$stripped" || "$stripped" == \#* ]] && continue

    var_name="${stripped%%=*}"

    if ! [[ "$var_name" =~ ^(${_DEPLOY_PATH_VARS})$ ]]; then
        app_vars_in_deploy+=("$var_name")
        log_info "  App config in deploy.env: $var_name"
    fi
done < "$DEPLOY_ENV"

if [ ${#app_vars_in_deploy[@]} -eq 0 ]; then
    log_success "deploy.env is already clean — no app config vars found"
else
    log_warning "Found ${#app_vars_in_deploy[@]} app config var(s) to migrate"
fi

# --- Step 3: Merge app config into docker/.env ---
log_info "Step 3: Merging app config from deploy.env into docker/.env"

merged_count=0
for var_name in "${app_vars_in_deploy[@]}"; do
    # Get value from deploy.env (this is what was actually running)
    deploy_val=$(grep -E "^(export )?${var_name}=" "$DEPLOY_ENV" | head -1 | sed "s/^[^=]*=//")

    if grep -qE "^${var_name}=" "$DOCKER_ENV"; then
        docker_val=$(grep -E "^${var_name}=" "$DOCKER_ENV" | head -1 | sed "s/^[^=]*=//")
        if [ "$deploy_val" != "$docker_val" ]; then
            log_warning "  CONFLICT: $var_name — deploy.env value wins (was actually running)"
            log_info "    deploy.env: $deploy_val"
            log_info "    docker/.env: $docker_val"
            if ! $DRY_RUN; then
                sed -i "s|^${var_name}=.*|${var_name}=${deploy_val}|" "$DOCKER_ENV"
            fi
            merged_count=$((merged_count + 1))
        else
            log_info "  OK: $var_name — same value in both files"
        fi
    else
        log_info "  NEW: $var_name — adding to docker/.env"
        if ! $DRY_RUN; then
            echo "${var_name}=${deploy_val}" >> "$DOCKER_ENV"
        fi
        merged_count=$((merged_count + 1))
    fi
done

log_success "Merged $merged_count var(s) into docker/.env"

# --- Step 4: Strip app config from deploy.env ---
log_info "Step 4: Reducing deploy.env to path vars only"

if ! $DRY_RUN; then
    cat > "$DEPLOY_ENV" <<'DEPLOY_HEADER'
# /etc/bisq-support/deploy.env
#
# Deploy-path variables ONLY. These are used by shell scripts (start.sh,
# update.sh, etc.) for repo URLs and installation directories.
#
# ALL app config (secrets, room IDs, feature flags) belongs in
# /opt/bisq-support/docker/.env — the single source of truth for
# Docker Compose.

DEPLOY_HEADER

    while IFS= read -r line || [ -n "$line" ]; do
        stripped="${line#"${line%%[![:space:]]*}"}"
        stripped="${stripped#export }"
        [[ -z "$stripped" || "$stripped" == \#* ]] && continue

        var_name="${stripped%%=*}"
        if [[ "$var_name" =~ ^(${_DEPLOY_PATH_VARS})$ ]]; then
            echo "export $stripped" >> "$DEPLOY_ENV"
        fi
    done < "$BACKUP_DIR/deploy.env.bak"

    log_success "deploy.env reduced to path vars only"
else
    log_info "  Would reduce deploy.env to path vars only"
fi

# --- Step 5: Apply Matrix room fixes ---
log_info "Step 5: Validating Matrix room configuration"

fix_env_var() {
    local var="$1" expected="$2" file="$3"
    local current
    current=$(grep -E "^${var}=" "$file" 2>/dev/null | head -1 | sed "s/^[^=]*=//" || true)

    if [ "$current" = "$expected" ]; then
        log_success "  $var already correct"
        return 0
    fi

    if [ -z "$current" ]; then
        log_warning "  $var: MISSING -> $expected"
        if ! $DRY_RUN; then
            echo "${var}=${expected}" >> "$file"
        fi
    else
        log_warning "  $var: $current -> $expected"
        if ! $DRY_RUN; then
            sed -i "s|^${var}=.*|${var}=${expected}|" "$file"
        fi
    fi
}

if $FIX_ROOMS; then
    fix_env_var "MATRIX_STAFF_ROOM" "!FtekSajHOJmxCkISRg:matrix.org" "$DOCKER_ENV"
    fix_env_var "TRUST_MONITOR_MATRIX_STAFF_ROOM" "!FtekSajHOJmxCkISRg:matrix.org" "$DOCKER_ENV"
else
    log_info "  Skipped room fix (--skip-room-fix)"
fi

# --- Step 6: Final validation ---
log_info "Step 6: Post-migration validation"

if ! $DRY_RUN; then
    echo ""
    log_info "=== deploy.env (should be ~4 path vars) ==="
    cat "$DEPLOY_ENV"
    echo ""
    log_info "=== Matrix room config in docker/.env ==="
    grep -E "MATRIX_SYNC_ROOMS|MATRIX_STAFF_ROOM|MATRIX_CHATOPS_ROOM_IDS|TRUST_MONITOR_MATRIX" "$DOCKER_ENV" || true
    echo ""

    # Run the new validation
    if validate_app_env "$DOCKER_ENV"; then
        log_success "docker/.env passes app env validation"
    else
        log_error "docker/.env failed validation — check output above"
        log_info "Backups are at $BACKUP_DIR/ for rollback"
        exit 1
    fi

    if detect_env_shadowing "$DEPLOY_ENV" "$DOCKER_ENV"; then
        log_success "No shadowing detected"
    else
        log_warning "Shadowing still present — review deploy.env manually"
    fi
fi

echo ""
log_success "Migration complete!"
if ! $DRY_RUN; then
    log_info "Backups at: $BACKUP_DIR/"
    log_info "Restart with: cd /opt/bisq-support && scripts/restart.sh"
fi

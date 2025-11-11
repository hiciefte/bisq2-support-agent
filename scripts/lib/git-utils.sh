#!/bin/bash
# Git operations and version management utilities for Bisq Support Assistant

# Source common functions
LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck disable=SC1091
source "$LIB_DIR/common.sh"

# SECURITY: Git remote validation function
validate_git_remote() {
    local remote="$1"

    # Validate remote name format (alphanumeric, dash, underscore, dot)
    if [[ ! "$remote" =~ ^[a-zA-Z0-9._-]+$ ]]; then
        log_error "Invalid git remote name: $remote"
        return 1
    fi

    # Verify remote exists in repository
    if ! git remote | grep -q "^${remote}$"; then
        log_error "Git remote does not exist: $remote"
        return 1
    fi

    return 0
}

# SECURITY: Git branch validation function
validate_git_branch() {
    local branch="$1"

    # Validate branch name format (alphanumeric, dash, underscore, slash, dot)
    if [[ ! "$branch" =~ ^[a-zA-Z0-9._/-]+$ ]]; then
        log_error "Invalid git branch name: $branch"
        return 1
    fi

    return 0
}

# Function to check for local changes
check_local_changes() {
    local repo_dir="${1:-.}"

    cd "$repo_dir" || {
        log_error "Failed to change to repository directory: $repo_dir"
        return 2
    }

    if ! validate_git_repo "$repo_dir"; then
        return 2
    fi

    if ! git diff-index --quiet HEAD --; then
        return 0  # Has local changes
    else
        return 1  # No local changes
    fi
}

# Function to stash local changes
stash_changes() {
    local repo_dir="${1:-.}"
    local stash_message="${2:-Auto-stashed by script on $(date)}"

    cd "$repo_dir" || return 1

    log_warning "Local changes detected. Stashing changes..."
    if ! git stash push -m "$stash_message"; then
        log_error "Failed to stash local changes. Please commit or discard your changes."
        return 1
    fi

    log_success "Local changes stashed successfully"
    return 0
}

# Function to restore stashed changes
restore_stash() {
    local repo_dir="${1:-.}"

    cd "$repo_dir" || return 1

    log_info "Restoring local changes..."
    if ! git stash pop; then
        log_error "Failed to restore stashed changes. Your changes are still in the stash."
        log_warning "Run 'git stash list' and 'git stash apply' manually."
        return 1
    fi

    log_success "Local changes restored successfully"
    return 0
}

# Function to fetch latest changes from remote
fetch_remote() {
    local repo_dir="${1:-.}"
    local remote="${2:-${GIT_REMOTE:-origin}}"

    cd "$repo_dir" || return 1

    # SECURITY: Validate remote name before using it
    if ! validate_git_remote "$remote"; then
        return 1
    fi

    log_info "Fetching latest changes from $remote..."
    if ! git fetch "$remote"; then
        log_error "Failed to fetch latest changes from $remote"
        log_error "Check your network connection or repository access"
        return 1
    fi

    log_success "Fetched latest changes from $remote"
    return 0
}

# Function to reset to remote branch
reset_to_remote() {
    local repo_dir="${1:-.}"
    local remote="${2:-${GIT_REMOTE:-origin}}"
    local branch="${3:-${GIT_BRANCH:-main}}"

    cd "$repo_dir" || return 1

    # SECURITY: Validate remote and branch names before using them
    if ! validate_git_remote "$remote"; then
        return 1
    fi

    if ! validate_git_branch "$branch"; then
        return 1
    fi

    log_info "Resetting to $remote/$branch to ensure consistency..."
    if ! git reset --hard "$remote/$branch"; then
        log_error "Failed to reset to $remote/$branch"
        return 1
    fi

    log_success "Reset to $remote/$branch successfully"
    return 0
}

# Function to preserve production data files during deployment
preserve_production_data() {
    local repo_dir="${1:-.}"

    # SECURITY: Canonicalize path to prevent traversal attacks
    repo_dir=$(realpath -e "$repo_dir" 2>/dev/null) || {
        log_error "Repository directory does not exist: ${1:-.}"
        return 1
    }

    # SECURITY: Validate path structure (must contain bisq-support or be a test directory)
    if [[ ! "$repo_dir" =~ (bisq-support|bisq.*test) ]]; then
        log_error "Invalid repository directory: $repo_dir"
        return 1
    fi

    cd "$repo_dir" || {
        log_error "Failed to change to repository directory: $repo_dir"
        return 1
    }

    # SECURITY: Add file locking to prevent race conditions
    local lock_file="$repo_dir/api/data/.backup.lock"
    exec 200>"$lock_file"
    if ! flock -x -w 30 200; then
        log_error "Could not acquire backup lock (another backup in progress)"
        return 1
    fi

    # Add PID to backup directory name for uniqueness
    local backup_dir="$repo_dir/api/data/.backup_$(date +%Y%m%d_%H%M%S)_$$"

    # Files that should never be overwritten by git (dynamic production data)
    local production_files=(
        "api/data/extracted_faq.jsonl"
        "api/data/processed_message_ids.jsonl"
        "api/data/conversations.jsonl"
    )

    # Create backup directory with restrictive permissions
    mkdir -p "$backup_dir"
    chmod 700 "$backup_dir"

    log_info "Backing up production data files..."
    local backed_up_count=0
    local max_file_size=$((50 * 1024 * 1024))  # 50MB limit

    for file in "${production_files[@]}"; do
        local file_path="$repo_dir/$file"

        # SECURITY: Validate file type and permissions
        if [ ! -f "$file_path" ] || [ -L "$file_path" ]; then
            log_debug "Skipping non-regular file: $file"
            continue
        fi

        # SECURITY: Check file size to prevent disk exhaustion
        local file_size=$(stat -c%s "$file_path" 2>/dev/null || stat -f%z "$file_path" 2>/dev/null)
        if [ "$file_size" -gt "$max_file_size" ]; then
            log_warning "Skipping oversized file (>50MB): $file"
            continue
        fi

        # SECURITY: Verify file is readable
        if [ ! -r "$file_path" ]; then
            log_error "Cannot read file: $file"
            flock -u 200
            return 1
        fi

        # Use -- to prevent filename interpretation
        cp -- "$file_path" "$backup_dir/"
        backed_up_count=$((backed_up_count + 1))
        log_debug "Backed up: $file"
    done

    # Release lock
    flock -u 200

    if [ "$backed_up_count" -gt 0 ]; then
        log_success "Backed up $backed_up_count production data file(s) to: $backup_dir"
        echo "$backup_dir"
        return 0
    else
        log_warning "No production data files found to backup"
        rmdir "$backup_dir" 2>/dev/null
        return 0
    fi
}

# Function to restore production data files after deployment
restore_production_data() {
    local repo_dir="${1:-.}"
    local backup_dir="${2}"

    if [ -z "$backup_dir" ] || [ ! -d "$backup_dir" ]; then
        log_debug "No production data to restore (expected on initial deployment or when no data files exist)"
        return 0
    fi

    # SECURITY: Canonicalize paths to prevent traversal attacks
    repo_dir=$(realpath -e "$repo_dir" 2>/dev/null) || {
        log_error "Repository directory does not exist"
        return 1
    }

    backup_dir=$(realpath -e "$backup_dir" 2>/dev/null) || {
        log_error "Backup directory does not exist"
        return 1
    }

    cd "$repo_dir" || return 1

    log_info "Restoring production data files from backup..."
    local restored_count=0

    # SECURITY: Use whitelist of allowed files instead of dynamic iteration
    local allowed_files=(
        "extracted_faq.jsonl"
        "processed_message_ids.jsonl"
        "conversations.jsonl"
    )

    for allowed_file in "${allowed_files[@]}"; do
        local backup_file="$backup_dir/$allowed_file"

        # SECURITY: Verify file exists, is regular file, and not a symlink
        if [ ! -f "$backup_file" ] || [ -L "$backup_file" ]; then
            log_debug "Skipping non-existent or invalid file: $allowed_file"
            continue
        fi

        # SECURITY: Verify file is readable
        if [ ! -r "$backup_file" ]; then
            log_warning "Cannot read backup file: $allowed_file"
            continue
        fi

        local restore_path="$repo_dir/api/data/$allowed_file"

        # Use -- to prevent filename interpretation
        cp -- "$backup_file" "$restore_path"
        restored_count=$((restored_count + 1))
        log_debug "Restored: $allowed_file"
    done

    if [ "$restored_count" -gt 0 ]; then
        log_success "Restored $restored_count production data file(s)"
        # Keep backup for safety (cleanup will handle old ones)
        return 0
    else
        log_warning "No files found in backup directory"
        return 0
    fi
}

# Function to run FAQ schema migration
run_faq_migration() {
    local repo_dir="${1:-.}"
    local migration_script="$repo_dir/scripts/migrate_faq_schema.py"

    cd "$repo_dir" || return 1

    if [ ! -f "$migration_script" ]; then
        log_warning "FAQ migration script not found: $migration_script"
        return 0
    fi

    log_info "Running FAQ schema migration..."

    # Make script executable
    chmod +x "$migration_script"

    # SECURITY: Pass data directory explicitly
    local data_dir="$repo_dir/api/data"

    # Run migration with --data-dir argument
    if python3 "$migration_script" --data-dir "$data_dir"; then
        log_success "FAQ schema migration completed"
        return 0
    else
        log_error "FAQ schema migration failed"
        return 1
    fi
}

# Function to update repository with stash handling and production data preservation
update_repository() {
    local repo_dir="${1:-.}"
    local remote="${2:-${GIT_REMOTE:-origin}}"
    local branch="${3:-${GIT_BRANCH:-main}}"
    local stashed=false
    local data_backup_dir=""

    cd "$repo_dir" || {
        log_error "Failed to change to repository directory: $repo_dir"
        return 1
    }

    # Validate git repository
    if ! validate_git_repo "$repo_dir"; then
        return 1
    fi

    # CRITICAL: Preserve production data BEFORE any git operations
    data_backup_dir=$(preserve_production_data "$repo_dir")

    # Check for local changes and stash if needed
    if check_local_changes "$repo_dir"; then
        if ! stash_changes "$repo_dir"; then
            return 1
        fi
        stashed=true
    else
        log_success "No local changes detected"
    fi

    # Record current HEAD before pull
    log_info "Recording current git HEAD hash before pull..."
    PREV_HEAD=$(git rev-parse HEAD)
    if [ -z "$PREV_HEAD" ]; then
        log_error "Failed to get current HEAD"
        return 1
    fi
    export PREV_HEAD
    export DATA_BACKUP_DIR="$data_backup_dir"  # Export for rollback access

    # Fetch latest changes
    if ! fetch_remote "$repo_dir" "$remote"; then
        if $stashed; then
            restore_stash "$repo_dir"
        fi
        # Restore production data on failure
        if [ -n "$data_backup_dir" ]; then
            restore_production_data "$repo_dir" "$data_backup_dir"
        fi
        return 1
    fi

    # Reset to remote branch
    if ! reset_to_remote "$repo_dir" "$remote" "$branch"; then
        if $stashed; then
            restore_stash "$repo_dir"
        fi
        # Restore production data on failure
        if [ -n "$data_backup_dir" ]; then
            restore_production_data "$repo_dir" "$data_backup_dir"
        fi
        return 1
    fi

    # CRITICAL: Restore production data AFTER git reset
    if [ -n "$data_backup_dir" ]; then
        if ! restore_production_data "$repo_dir" "$data_backup_dir"; then
            log_error "Failed to restore production data"
            return 1
        fi
    fi

    # Check if anything was updated
    local current_head
    current_head=$(git rev-parse HEAD)
    if [ "$PREV_HEAD" = "$current_head" ]; then
        log_success "Already up to date. No changes found on $remote/$branch"

        # Restore stashed changes if any
        if $stashed; then
            restore_stash "$repo_dir"
        fi

        return 2  # Special return code for "no updates"
    fi

    # Show what was updated
    log_success "Updates pulled successfully!"
    log_info "Changes in this update:"
    git log --oneline --no-merges --max-count=10 "${PREV_HEAD}..HEAD"

    # Run FAQ schema migration after code update
    if ! run_faq_migration "$repo_dir"; then
        log_warning "FAQ migration had issues, but continuing deployment"
    fi

    # Restore stashed changes after update
    if $stashed; then
        if ! restore_stash "$repo_dir"; then
            log_error "There were conflicts when restoring local changes"
            log_error "Please resolve them manually before proceeding"
            return 1
        fi
    fi

    return 0
}

# Function to check if rebuild is needed based on file changes
needs_rebuild() {
    local repo_dir="${1:-.}"
    local prev_head="${2:-$PREV_HEAD}"

    cd "$repo_dir" || return 2

    # Fallback for CI/CD or environments where reflog might not be available
    if [ -z "$(git reflog show -n 1 2>/dev/null)" ]; then
        # Use git merge-base for branch comparison
        local base
        base=$(git merge-base HEAD "${GIT_REMOTE:-origin}/${GIT_BRANCH:-main}" 2>/dev/null || git rev-parse HEAD~1 2>/dev/null)
        if [ -n "$base" ]; then
            if git diff --name-only "$base" HEAD | grep -qE 'Dockerfile|requirements.txt|package.json|package-lock.json|yarn.lock'; then
                return 0  # True, needs rebuild
            fi
        else
            log_warning "Unable to determine git base for comparison. Assuming rebuild needed"
            return 0
        fi
    else
        # Standard approach using previous head
        if [ -n "$prev_head" ]; then
            if git diff --name-only "$prev_head" HEAD | grep -qE 'Dockerfile|requirements.txt|package.json|package-lock.json|yarn.lock'; then
                return 0  # True, needs rebuild
            fi
        else
            # Use HEAD@{1} as fallback
            if git diff --name-only "HEAD@{1}" HEAD | grep -qE 'Dockerfile|requirements.txt|package.json|package-lock.json|yarn.lock'; then
                return 0  # True, needs rebuild
            fi
        fi
    fi

    return 1  # False, no rebuild needed
}

# Function to check if API restart is needed
needs_api_restart() {
    local repo_dir="${1:-.}"
    local prev_head="${2:-$PREV_HEAD}"

    cd "$repo_dir" || return 2

    if [ -z "$(git reflog show -n 1 2>/dev/null)" ]; then
        local base
        base=$(git merge-base HEAD "${GIT_REMOTE:-origin}/${GIT_BRANCH:-main}" 2>/dev/null || git rev-parse HEAD~1 2>/dev/null)
        if [ -n "$base" ]; then
            if git diff --name-only "$base" HEAD | grep -qE '^api/'; then
                return 0  # True, needs restart
            fi
        else
            log_warning "Unable to determine git base for comparison. Assuming API restart needed"
            return 0
        fi
    else
        if [ -n "$prev_head" ]; then
            if git diff --name-only "$prev_head" HEAD | grep -qE '^api/'; then
                return 0  # True, needs restart
            fi
        else
            if git diff --name-only "HEAD@{1}" HEAD | grep -qE '^api/'; then
                return 0  # True, needs restart
            fi
        fi
    fi

    return 1  # False, no restart needed
}

# Function to check if Web restart is needed
needs_web_restart() {
    local repo_dir="${1:-.}"
    local prev_head="${2:-$PREV_HEAD}"

    cd "$repo_dir" || return 2

    if [ -z "$(git reflog show -n 1 2>/dev/null)" ]; then
        local base
        base=$(git merge-base HEAD "${GIT_REMOTE:-origin}/${GIT_BRANCH:-main}" 2>/dev/null || git rev-parse HEAD~1 2>/dev/null)
        if [ -n "$base" ]; then
            if git diff --name-only "$base" HEAD | grep -qE '^web/'; then
                return 0  # True, needs restart
            fi
        else
            log_warning "Unable to determine git base for comparison. Assuming web restart needed"
            return 0
        fi
    else
        if [ -n "$prev_head" ]; then
            if git diff --name-only "$prev_head" HEAD | grep -qE '^web/'; then
                return 0  # True, needs restart
            fi
        else
            if git diff --name-only "HEAD@{1}" HEAD | grep -qE '^web/'; then
                return 0  # True, needs restart
            fi
        fi
    fi

    return 1  # False, no restart needed
}

# Function to check if Nginx restart is needed
needs_nginx_restart() {
    local repo_dir="${1:-.}"
    local prev_head="${2:-$PREV_HEAD}"

    cd "$repo_dir" || return 2

    if [ -z "$(git reflog show -n 1 2>/dev/null)" ]; then
        local base
        base=$(git merge-base HEAD "${GIT_REMOTE:-origin}/${GIT_BRANCH:-main}" 2>/dev/null || git rev-parse HEAD~1 2>/dev/null)
        if [ -n "$base" ]; then
            if git diff --name-only "$base" HEAD | grep -qE '^docker/nginx/'; then
                return 0  # True, needs restart
            fi
        else
            log_warning "Unable to determine git base for comparison. Assuming nginx restart needed"
            return 0
        fi
    else
        if [ -n "$prev_head" ]; then
            if git diff --name-only "$prev_head" HEAD | grep -qE '^docker/nginx/'; then
                return 0  # True, needs restart
            fi
        else
            if git diff --name-only "HEAD@{1}" HEAD | grep -qE '^docker/nginx/'; then
                return 0  # True, needs restart
            fi
        fi
    fi

    return 1  # False, no restart needed
}

# Function to create a backup reference
create_backup_reference() {
    local repo_dir="${1:-.}"
    local backup_name="${2:-backup-$(date +%Y%m%d_%H%M%S)}"

    cd "$repo_dir" || return 1

    log_info "Creating backup reference: $backup_name"
    if ! git tag "$backup_name"; then
        log_error "Failed to create backup reference"
        return 1
    fi

    log_success "Backup reference created: $backup_name"
    echo "$backup_name"
    return 0
}

# Function to rollback to a specific reference
rollback_to_ref() {
    local repo_dir="${1:-.}"
    local ref="${2:-$PREV_HEAD}"

    cd "$repo_dir" || return 1

    # Verify ref is valid
    if [ -z "$ref" ] || ! git rev-parse --verify "$ref" >/dev/null 2>&1; then
        log_error "Invalid or missing reference: $ref"
        return 1
    fi

    log_info "Rolling back to: $ref"
    if ! git reset --hard "$ref"; then
        log_error "Failed to reset to $ref"
        return 1
    fi

    log_success "Rolled back to $ref successfully"
    return 0
}

# Function to get the latest backup tag
get_latest_backup() {
    local repo_dir="${1:-.}"

    cd "$repo_dir" || return 1

    local latest_backup
    latest_backup=$(git tag -l "backup-*" --sort=-creatordate | head -n 1)

    if [ -z "$latest_backup" ]; then
        log_error "No backup tags found"
        return 1
    fi

    echo "$latest_backup"
    return 0
}

# Function to list all backup tags
list_backups() {
    local repo_dir="${1:-.}"
    local limit="${2:-10}"

    cd "$repo_dir" || return 1

    log_info "Available backup tags (most recent first):"
    git tag -l "backup-*" --sort=-creatordate | head -n "$limit"
}

# Function to delete old backup tags
cleanup_old_backups() {
    local repo_dir="${1:-.}"
    local keep_count="${2:-5}"

    cd "$repo_dir" || return 1

    local backup_count
    backup_count=$(git tag -l "backup-*" | wc -l)

    if [ "$backup_count" -le "$keep_count" ]; then
        log_info "No old backups to clean up (current: $backup_count, keeping: $keep_count)"
        return 0
    fi

    log_info "Cleaning up old backup tags (keeping $keep_count most recent)..."
    local old_backups
    old_backups=$(git tag -l "backup-*" --sort=-creatordate | tail -n +$((keep_count + 1)))

    for tag in $old_backups; do
        log_debug "Deleting old backup tag: $tag"
        git tag -d "$tag" >/dev/null 2>&1
    done

    log_success "Old backup tags cleaned up"
    return 0
}

# Export all functions
export -f check_local_changes
export -f stash_changes
export -f restore_stash
export -f fetch_remote
export -f reset_to_remote
export -f preserve_production_data
export -f restore_production_data
export -f run_faq_migration
export -f update_repository
export -f needs_rebuild
export -f needs_api_restart
export -f needs_web_restart
export -f needs_nginx_restart
export -f create_backup_reference
export -f rollback_to_ref
export -f get_latest_backup
export -f list_backups
export -f cleanup_old_backups

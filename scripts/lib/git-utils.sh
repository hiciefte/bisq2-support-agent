#!/bin/bash
# Git operations and version management utilities for Bisq Support Assistant

# Source common functions
LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck disable=SC1091
source "$LIB_DIR/common.sh"

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

    log_info "Resetting to $remote/$branch to ensure consistency..."
    if ! git reset --hard "$remote/$branch"; then
        log_error "Failed to reset to $remote/$branch"
        return 1
    fi

    log_success "Reset to $remote/$branch successfully"
    return 0
}

# Function to update repository with stash handling
update_repository() {
    local repo_dir="${1:-.}"
    local remote="${2:-${GIT_REMOTE:-origin}}"
    local branch="${3:-${GIT_BRANCH:-main}}"
    local stashed=false

    cd "$repo_dir" || {
        log_error "Failed to change to repository directory: $repo_dir"
        return 1
    }

    # Validate git repository
    if ! validate_git_repo "$repo_dir"; then
        return 1
    fi

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

    # Fetch latest changes
    if ! fetch_remote "$repo_dir" "$remote"; then
        if $stashed; then
            restore_stash "$repo_dir"
        fi
        return 1
    fi

    # Reset to remote branch
    if ! reset_to_remote "$repo_dir" "$remote" "$branch"; then
        if $stashed; then
            restore_stash "$repo_dir"
        fi
        return 1
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

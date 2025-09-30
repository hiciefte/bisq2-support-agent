#!/bin/bash
#
# Automated Personal Data Cleanup Script
#
# This script removes personal data files older than the configured retention period.
# It implements GDPR-compliant data retention policies by automatically deleting
# conversation data that exceeds the retention limit.
#
# Usage:
#   ./cleanup_personal_data.sh
#
# Environment Variables:
#   DATA_RETENTION_DAYS - Number of days to retain data (default: 30)
#   DATA_DIR - Path to data directory (default: api/data)

set -e

# Configuration
RETENTION_DAYS=${DATA_RETENTION_DAYS:-30}
DATA_DIR=${DATA_DIR:-"api/data"}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Logging function
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

log "Starting personal data cleanup (retention period: ${RETENTION_DAYS} days)"

# Files to clean up
FILES_TO_CLEANUP=(
    "conversations.jsonl"
    "processed_conversations.json"
    "processed_message_ids.jsonl"
    "support_chat_export.csv"
)

# Change to data directory
cd "${PROJECT_ROOT}/${DATA_DIR}" || {
    log "ERROR: Data directory not found: ${PROJECT_ROOT}/${DATA_DIR}"
    exit 1
}

log "Working directory: $(pwd)"

# Count files before cleanup
total_files=0
files_deleted=0

# Cleanup old files
for file_pattern in "${FILES_TO_CLEANUP[@]}"; do
    # Find and delete files older than retention period
    while IFS= read -r -d '' file; do
        total_files=$((total_files + 1))
        if [ -n "$file" ]; then
            log "Deleting: $file"
            rm -f "$file"
            files_deleted=$((files_deleted + 1))
        fi
    done < <(find . -maxdepth 1 -name "$file_pattern" -type f -mtime "+${RETENTION_DAYS}" -print0 2>/dev/null)
done

# Report results
log "Cleanup complete: ${files_deleted}/${total_files} files deleted"

# Optional: cleanup empty directories
find . -type d -empty -delete 2>/dev/null || true

log "Personal data cleanup finished successfully"
exit 0
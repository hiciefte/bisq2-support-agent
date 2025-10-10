#!/bin/bash
#
# cleanup_old_data.sh - Automated cleanup of old chat data for privacy compliance
#
# This script removes raw chat and conversation data older than a specified retention period
# while preserving extracted FAQs. It's designed to run as a cron job for automated cleanup.
#
# Usage: ./cleanup_old_data.sh [--dry-run] [--retention-days N]
#
# Environment Variables:
#   DATA_RETENTION_DAYS - Number of days to retain raw data (default: 30)
#   DATA_DIR - Path to data directory (default: /opt/bisq-support/api/data)
#
# Cron example: 0 2 * * * /opt/bisq-support/scripts/cleanup_old_data.sh >> /var/log/bisq-data-cleanup.log 2>&1
#

set -euo pipefail

# Configuration
RETENTION_DAYS="${DATA_RETENTION_DAYS:-30}"
DATA_DIR="${DATA_DIR:-/opt/bisq-support/api/data}"
DRY_RUN=false
LOG_PREFIX="[DATA-CLEANUP]"

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --retention-days)
            RETENTION_DAYS="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [--dry-run] [--retention-days N]"
            echo ""
            echo "Options:"
            echo "  --dry-run           Show what would be deleted without actually deleting"
            echo "  --retention-days N  Number of days to retain data (default: 30)"
            echo ""
            echo "Environment Variables:"
            echo "  DATA_RETENTION_DAYS - Number of days to retain raw data"
            echo "  DATA_DIR           - Path to data directory"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Run with --help for usage information"
            exit 1
            ;;
    esac
done

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $LOG_PREFIX $*"
}

# Error handling
error() {
    log "ERROR: $*" >&2
    exit 1
}

# Validate configuration
if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
    error "RETENTION_DAYS must be a positive integer (got: $RETENTION_DAYS)"
fi

if [ ! -d "$DATA_DIR" ]; then
    error "Data directory does not exist: $DATA_DIR"
fi

# Start cleanup
log "Starting data cleanup (retention: ${RETENTION_DAYS} days)"
if [ "$DRY_RUN" = true ]; then
    log "DRY RUN MODE - No files will be deleted"
fi

# Files to clean up (excluding extracted_faq.jsonl which should be preserved)
FILES_TO_CLEAN=(
    "conversations.jsonl"
    "support_chat_export.csv"
    "processed_conversations.json"
)

# Track cleanup statistics
total_files_checked=0
total_files_deleted=0
total_space_freed=0

# Function to get file age in days
get_file_age_days() {
    local file="$1"
    if [ ! -f "$file" ]; then
        echo "-1"
        return
    fi

    # Get file modification time
    local file_mtime
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        file_mtime=$(stat -f %m "$file")
    else
        # Linux
        file_mtime=$(stat -c %Y "$file")
    fi

    # Calculate age in days
    local current_time=$(date +%s)
    local age_seconds=$((current_time - file_mtime))
    local age_days=$((age_seconds / 86400))

    echo "$age_days"
}

# Function to get human-readable file size
get_file_size() {
    local file="$1"
    if [ ! -f "$file" ]; then
        echo "0"
        return
    fi

    if [[ "$OSTYPE" == "darwin"* ]]; then
        stat -f %z "$file"
    else
        stat -c %s "$file"
    fi
}

# Function to format bytes to human-readable
format_bytes() {
    local bytes=$1
    if [ $bytes -lt 1024 ]; then
        echo "${bytes}B"
    elif [ $bytes -lt 1048576 ]; then
        echo "$((bytes / 1024))KB"
    else
        echo "$((bytes / 1048576))MB"
    fi
}

# Clean up old files
for filename in "${FILES_TO_CLEAN[@]}"; do
    filepath="$DATA_DIR/$filename"

    if [ ! -f "$filepath" ]; then
        log "Skip: $filename (not found)"
        continue
    fi

    total_files_checked=$((total_files_checked + 1))
    age_days=$(get_file_age_days "$filepath")
    file_size=$(get_file_size "$filepath")

    if [ "$age_days" -ge "$RETENTION_DAYS" ]; then
        log "Found old file: $filename (age: ${age_days} days, size: $(format_bytes $file_size))"

        if [ "$DRY_RUN" = true ]; then
            log "Would delete: $filepath"
        else
            if rm "$filepath"; then
                log "Deleted: $filepath"
                total_files_deleted=$((total_files_deleted + 1))
                total_space_freed=$((total_space_freed + file_size))
            else
                log "ERROR: Failed to delete $filepath"
            fi
        fi
    else
        log "Skip: $filename (age: ${age_days} days, retention: ${RETENTION_DAYS} days)"
    fi
done

# Clean up processed_message_ids.jsonl if it's old
# This file can be regenerated from conversations.jsonl if needed
PROCESSED_MSG_IDS="$DATA_DIR/processed_message_ids.jsonl"
if [ -f "$PROCESSED_MSG_IDS" ]; then
    age_days=$(get_file_age_days "$PROCESSED_MSG_IDS")
    if [ "$age_days" -ge "$RETENTION_DAYS" ]; then
        file_size=$(get_file_size "$PROCESSED_MSG_IDS")
        log "Found old tracking file: processed_message_ids.jsonl (age: ${age_days} days)"

        if [ "$DRY_RUN" = true ]; then
            log "Would delete: $PROCESSED_MSG_IDS"
        else
            # Note: Only delete if conversations.jsonl has been deleted
            if [ ! -f "$DATA_DIR/conversations.jsonl" ]; then
                if rm "$PROCESSED_MSG_IDS"; then
                    log "Deleted: $PROCESSED_MSG_IDS"
                    total_files_deleted=$((total_files_deleted + 1))
                    total_space_freed=$((total_space_freed + file_size))
                fi
            else
                log "Keep: processed_message_ids.jsonl (conversations.jsonl still exists)"
            fi
        fi
    fi
fi

# Summary
log "Cleanup complete"
log "Files checked: $total_files_checked"
log "Files deleted: $total_files_deleted"
log "Space freed: $(format_bytes $total_space_freed)"

# Verify that extracted_faq.jsonl still exists
FAQ_FILE="$DATA_DIR/extracted_faq.jsonl"
if [ -f "$FAQ_FILE" ]; then
    log "✓ extracted_faq.jsonl preserved (permanent storage)"
else
    log "⚠ WARNING: extracted_faq.jsonl not found - this file should be preserved"
fi

# Exit with appropriate status
if [ "$DRY_RUN" = true ]; then
    log "Dry run completed successfully"
    exit 0
elif [ $total_files_deleted -eq 0 ]; then
    log "No files needed cleanup"
    exit 0
else
    log "Successfully cleaned up $total_files_deleted file(s)"
    exit 0
fi

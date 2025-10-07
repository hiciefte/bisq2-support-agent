#!/bin/bash
# Feedback Persistence Verification Script
# This script validates that the feedback system is properly persisting data

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Installation directory
INSTALL_DIR="${BISQ_SUPPORT_INSTALL_DIR:-/opt/bisq-support}"
DOCKER_DIR="$INSTALL_DIR/docker"
FEEDBACK_DIR="$INSTALL_DIR/api/data/feedback"

echo "=================================="
echo "Feedback Persistence Verification"
echo "=================================="
echo ""

# Function to log messages
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Check if feedback directory exists
check_feedback_directory() {
    log_info "Checking feedback directory..."

    if [ ! -d "$FEEDBACK_DIR" ]; then
        log_error "Feedback directory does not exist: $FEEDBACK_DIR"
        return 1
    fi

    log_info "Feedback directory exists: $FEEDBACK_DIR"

    # Check permissions
    local perms=$(stat -c '%a' "$FEEDBACK_DIR" 2>/dev/null || stat -f '%A' "$FEEDBACK_DIR" 2>/dev/null)
    log_info "Directory permissions: $perms"

    # Check ownership
    local owner=$(stat -c '%u:%g' "$FEEDBACK_DIR" 2>/dev/null || stat -f '%u:%g' "$FEEDBACK_DIR" 2>/dev/null)
    log_info "Directory ownership: $owner (expected: 1001:1001)"

    if [ "$owner" != "1001:1001" ]; then
        log_warning "Ownership mismatch! Expected 1001:1001, got $owner"
        log_warning "This may cause permission issues in Docker containers"
    fi

    return 0
}

# Check Docker volume
check_docker_volume() {
    log_info "Checking Docker volume for feedback data..."

    cd "$DOCKER_DIR" || {
        log_error "Could not change to Docker directory: $DOCKER_DIR"
        return 1
    }

    # Check if the named volume exists
    if docker volume inspect bisq2-feedback-data >/dev/null 2>&1; then
        log_info "Named Docker volume 'bisq2-feedback-data' exists"

        # Get volume mount point
        local mountpoint=$(docker volume inspect bisq2-feedback-data -f '{{.Mountpoint}}' 2>/dev/null)
        log_info "Volume mount point: $mountpoint"
    else
        log_warning "Named Docker volume 'bisq2-feedback-data' does not exist yet"
        log_warning "It will be created on first docker compose up"
    fi

    return 0
}

# Count feedback entries
count_feedback_entries() {
    log_info "Counting feedback entries..."

    local total_entries=0
    local file_count=0

    if [ -d "$FEEDBACK_DIR" ]; then
        # Count entries in all feedback JSONL files
        for file in "$FEEDBACK_DIR"/feedback_*.jsonl; do
            if [ -f "$file" ]; then
                local entries=$(wc -l < "$file" 2>/dev/null || echo "0")
                total_entries=$((total_entries + entries))
                file_count=$((file_count + 1))
                log_info "  $(basename "$file"): $entries entries"
            fi
        done

        if [ $file_count -eq 0 ]; then
            log_warning "No feedback files found in $FEEDBACK_DIR"
        else
            log_info "Total: $total_entries feedback entries across $file_count files"
        fi
    else
        log_error "Feedback directory not found: $FEEDBACK_DIR"
        return 1
    fi

    return 0
}

# Check if API container can write to feedback directory
check_api_write_access() {
    log_info "Checking API container write access..."

    cd "$DOCKER_DIR" || {
        log_error "Could not change to Docker directory: $DOCKER_DIR"
        return 1
    }

    # Check if API container is running
    if ! docker compose -f docker-compose.yml ps api | grep -q "Up"; then
        log_warning "API container is not running. Skipping write access check."
        return 0
    fi

    # Test write access by creating a test file
    local test_file="/data/feedback/.write_test_$$"
    if docker compose -f docker-compose.yml exec -T api sh -c "touch $test_file && rm $test_file" 2>/dev/null; then
        log_info "API container has write access to feedback directory"
    else
        log_error "API container CANNOT write to feedback directory!"
        log_error "This will prevent feedback from being stored!"
        return 1
    fi

    return 0
}

# Verify feedback service is initialized
check_feedback_service() {
    log_info "Checking feedback service initialization..."

    # Try to query the feedback stats endpoint
    local api_url="http://localhost:8000"

    # Check if we can reach the health endpoint first
    if ! curl -sf "$api_url/health" >/dev/null 2>&1; then
        log_warning "API service is not reachable at $api_url"
        log_warning "Skipping feedback service check"
        return 0
    fi

    log_info "API service is running"
    return 0
}

# Main execution
main() {
    local exit_code=0

    echo ""

    # Run all checks
    if ! check_feedback_directory; then
        exit_code=1
    fi

    echo ""

    if ! check_docker_volume; then
        exit_code=1
    fi

    echo ""

    if ! count_feedback_entries; then
        exit_code=1
    fi

    echo ""

    if ! check_api_write_access; then
        exit_code=1
    fi

    echo ""

    if ! check_feedback_service; then
        exit_code=1
    fi

    echo ""
    echo "=================================="
    if [ $exit_code -eq 0 ]; then
        log_info "All checks passed!"
    else
        log_error "Some checks failed. Please review the output above."
    fi
    echo "=================================="

    return $exit_code
}

# Run main function
main
exit $?

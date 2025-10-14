#!/bin/bash
# Common utilities and configuration for Bisq Support Assistant scripts

# Colors and formatting
setup_colors() {
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m' # No Color
}

# Logging functions
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

log_debug() {
    if [ "${DEBUG:-false}" = "true" ]; then
        echo -e "${BLUE}🔍 $1${NC}"
    fi
}

# Environment detection
get_project_root() {
    # Get the directory of the calling script
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[1]}")" &>/dev/null && pwd)"
    echo "$script_dir/.."
}

get_script_dir() {
    echo "$(cd "$(dirname "${BASH_SOURCE[1]}")" &>/dev/null && pwd)"
}

# Validate required commands
check_required_commands() {
    local missing_commands=()

    for cmd in "$@"; do
        if ! command -v "$cmd" &> /dev/null; then
            missing_commands+=("$cmd")
        fi
    done

    if [ ${#missing_commands[@]} -gt 0 ]; then
        log_error "Required commands not found: ${missing_commands[*]}"
        return 1
    fi

    return 0
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        return 1
    fi
    return 0
}

# Check if Docker daemon is running
check_docker_daemon() {
    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running"
        return 1
    fi
    return 0
}

# Check if Docker Compose is available
check_docker_compose() {
    if ! docker compose version &> /dev/null; then
        log_error "Docker Compose plugin is not installed or not working"
        return 1
    fi
    return 0
}

# Source environment configuration
source_env_file() {
    local env_file="${1:-/etc/bisq-support/deploy.env}"

    if [ -f "$env_file" ]; then
        log_info "Sourcing environment variables from $env_file"
        # shellcheck disable=SC1090,SC1091
        source "$env_file"
        return 0
    else
        log_warning "Environment file $env_file not found. Using defaults."
        return 1
    fi
}

# Display banner
display_banner() {
    local title="$1"
    setup_colors
    echo -e "${BLUE}======================================================"
    echo -e "$title"
    echo -e "======================================================${NC}"
}

# Get container name based on service
get_container_name() {
    local service_name="$1"
    local docker_dir="${2:-$DOCKER_DIR}"

    # Use the directory name of DOCKER_DIR as the project name
    local project_name
    project_name=$(basename "$docker_dir")
    echo "${project_name}_${service_name}_1"
}

# Validate git repository
validate_git_repo() {
    local dir="${1:-.}"

    if [ ! -d "$dir/.git" ]; then
        log_error "Not a git repository: $dir"
        return 1
    fi
    return 0
}

# Initialize common environment variables
init_common_env() {
    # Export UID and GID for Docker Compose
    export APP_UID=${APP_UID:-1001}
    export APP_GID=${APP_GID:-1001}

    # Git configuration with defaults
    export GIT_REMOTE=${GIT_REMOTE:-origin}
    export GIT_BRANCH=${GIT_BRANCH:-main}

    # Installation directory
    export INSTALL_DIR=${BISQ_SUPPORT_INSTALL_DIR:-/opt/bisq-support}
    export DOCKER_DIR="${DOCKER_DIR:-$INSTALL_DIR/docker}"
    export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
}

# Trap for cleanup on exit
setup_cleanup_trap() {
    local cleanup_function="$1"
    trap "$cleanup_function" EXIT INT TERM
}

# Export all functions
export -f setup_colors
export -f log_info
export -f log_success
export -f log_warning
export -f log_error
export -f log_debug
export -f get_project_root
export -f get_script_dir
export -f check_required_commands
export -f check_root
export -f check_docker_daemon
export -f check_docker_compose
export -f source_env_file
export -f display_banner
export -f get_container_name
export -f validate_git_repo
export -f init_common_env
export -f setup_cleanup_trap

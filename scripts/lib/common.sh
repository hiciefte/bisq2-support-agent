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
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[1]}")" &>/dev/null && pwd)"
    echo "$script_dir/.."
}

get_script_dir() {
    cd "$(dirname "${BASH_SOURCE[1]}")" &>/dev/null && pwd
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

# Source environment configuration (legacy — kept for backward compatibility)
source_env_file() {
    local env_file="${1:-/etc/bisq-support/deploy.env}"

    if [ -f "$env_file" ]; then
        log_info "Sourcing environment variables from $env_file"
        # Export sourced values so docker compose interpolation sees deploy.env
        # without requiring operators to duplicate everything into docker/.env.
        set -a
        # shellcheck disable=SC1090,SC1091
        source "$env_file"
        set +a
        return 0
    else
        log_warning "Environment file $env_file not found. Using defaults."
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Single-source-of-truth env architecture
#
# deploy.env  → deploy-path vars ONLY (repo URLs, install dirs)
# docker/.env → ALL app config (secrets, room IDs, feature flags)
#
# Docker Compose reads docker/.env automatically. Scripts source deploy.env
# only for the handful of shell-only vars that Docker doesn't need.
# ---------------------------------------------------------------------------

# Allowed deploy-path variable prefixes/names.
# Everything else in deploy.env is considered app config (a shadowing risk).
_DEPLOY_PATH_VARS="BISQ_SUPPORT_INSTALL_DIR|BISQ_SUPPORT_REPO_URL|BISQ_SUPPORT_SECRETS_DIR|BISQ2_INSTALL_DIR|BISQ2_REPO_URL"

# Source ONLY deploy-path variables from deploy.env.
# App config vars are ignored so they cannot shadow docker/.env values.
source_deploy_paths() {
    local env_file="${1:-/etc/bisq-support/deploy.env}"

    if [ ! -f "$env_file" ]; then
        log_warning "Deploy paths file $env_file not found."
        return 1
    fi

    log_info "Sourcing deploy-path variables from $env_file"

    while IFS= read -r line || [ -n "$line" ]; do
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line#export }"
        [[ -z "$line" || "$line" == \#* ]] && continue

        local var_name="${line%%=*}"

        if [[ "$var_name" =~ ^(${_DEPLOY_PATH_VARS})$ ]]; then
            local var_val="${line#*=}"
            # Strip surrounding quotes if present
            var_val="${var_val#\"}" ; var_val="${var_val%\"}"
            var_val="${var_val#\'}" ; var_val="${var_val%\'}"
            export "${var_name}=${var_val}"
        fi
    done < "$env_file"

    return 0
}

# Validate that docker/.env (or a given env file) contains required Matrix
# room configuration. Returns non-zero if critical vars are missing.
validate_app_env() {
    local env_file="${1:-}"
    local errors=0
    local warnings=0

    if [ -z "$env_file" ]; then
        log_error "validate_app_env: no env file path provided"
        return 1
    fi

    if [ ! -f "$env_file" ]; then
        log_error "App env file not found: $env_file"
        return 1
    fi

    _env_has() { grep -qE "^${1}=.+" "$env_file"; }

    local required_vars=(
        "MATRIX_SYNC_ROOMS"
        "MATRIX_STAFF_ROOM"
    )

    for var in "${required_vars[@]}"; do
        if ! _env_has "$var"; then
            log_error "Required variable $var is missing or empty in $env_file"
            errors=$((errors + 1))
        fi
    done

    # Recommended vars (missing = warning)
    local recommended_vars=(
        "TRUST_MONITOR_MATRIX_PUBLIC_ROOMS"
        "TRUST_MONITOR_MATRIX_STAFF_ROOM"
    )

    for var in "${recommended_vars[@]}"; do
        if ! _env_has "$var"; then
            log_warning "Recommended variable $var is missing or empty in $env_file"
            warnings=$((warnings + 1))
        fi
    done

    unset -f _env_has

    if [ $errors -gt 0 ]; then
        log_error "App env validation failed: $errors error(s), $warnings warning(s)"
        return 1
    fi

    if [ $warnings -gt 0 ]; then
        log_warning "App env validation: $warnings warning(s)"
    fi

    return 0
}

# Detect app config vars in deploy.env that would shadow docker/.env.
# Returns non-zero if shadowing is found.
detect_env_shadowing() {
    local deploy_file="${1:-/etc/bisq-support/deploy.env}"
    local docker_file="${2:-}"
    local shadow_count=0

    if [ ! -f "$deploy_file" ] || [ ! -f "$docker_file" ]; then
        return 0  # Nothing to compare
    fi

    while IFS= read -r line || [ -n "$line" ]; do
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line#export }"
        [[ -z "$line" || "$line" == \#* ]] && continue

        local var_name="${line%%=*}"

        [[ "$var_name" =~ ^(${_DEPLOY_PATH_VARS})$ ]] && continue

        if grep -qE "^${var_name}=" "$docker_file"; then
            local deploy_val docker_val
            deploy_val="${line#*=}"
            docker_val=$(grep -E "^${var_name}=" "$docker_file" | head -1 | sed "s/^[^=]*=//")

            if [ "$deploy_val" != "$docker_val" ]; then
                log_warning "SHADOW CONFLICT: $var_name differs between deploy.env and docker/.env"
            else
                log_warning "SHADOW: $var_name exists in both deploy.env and docker/.env (same value)"
            fi
            shadow_count=$((shadow_count + 1))
        fi
    done < "$deploy_file"

    if [ $shadow_count -gt 0 ]; then
        log_error "Found $shadow_count app config var(s) in deploy.env that shadow docker/.env"
        log_info "Move app config to docker/.env and keep only path vars in deploy.env"
        return 1
    fi

    return 0
}

is_env_enabled() {
    local value="${1:-}"
    local normalized
    normalized=$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')
    case "$normalized" in
        1|true|yes|on)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

uses_qdrant_runtime() {
    true
}

_read_env_value() {
    local env_file="$1"
    local key="$2"

    awk -v key="$key" '
        index($0, key "=") == 1 {
            print substr($0, length(key) + 2)
            exit
        }
    ' "$env_file"
}

_write_env_value() {
    local env_file="$1"
    local key="$2"
    local value="$3"
    local env_tmp

    env_tmp=$(mktemp "${env_file}.tmp.XXXXXX") || return 1
    if ! awk -v key="$key" -v value="$value" '
        BEGIN { found = 0 }
        index($0, key "=") == 1 {
            if (!found) {
                print key "=" value
                found = 1
            }
            next
        }
        { print }
        END {
            if (!found) {
                print key "=" value
            }
        }
    ' "$env_file" > "$env_tmp"; then
        rm -f "$env_tmp"
        return 1
    fi

    chmod 600 "$env_tmp"
    mv "$env_tmp" "$env_file"
}

_secret_file_mode() {
    local secret_file="$1"

    if stat -c '%a' "$secret_file" >/dev/null 2>&1; then
        stat -c '%a' "$secret_file"
    else
        stat -f '%Lp' "$secret_file"
    fi
}

validate_grafana_runtime_secrets() {
    local env_file="$1"
    local secrets_dir="$2"
    local entry env_name secret_name env_value file_value mode
    local entries=(
        "GRAFANA_ADMIN_PASSWORD:grafana_admin_password"
        "GRAFANA_DATASOURCE_API_KEY:grafana_datasource_api_key"
    )

    if [ ! -f "$env_file" ]; then
        log_error "Grafana environment file not found: $env_file"
        return 1
    fi

    for entry in "${entries[@]}"; do
        env_name="${entry%%:*}"
        secret_name="${entry#*:}"
        env_value=$(_read_env_value "$env_file" "$env_name")

        if [ -z "$env_value" ]; then
            log_error "$env_name is missing or empty in $env_file"
            return 1
        fi

        if [ ! -s "$secrets_dir/$secret_name" ]; then
            log_error "Grafana secret file is missing or empty: $secrets_dir/$secret_name"
            return 1
        fi

        file_value=$(cat "$secrets_dir/$secret_name")
        if [ "$env_value" != "$file_value" ]; then
            log_error "$env_name differs from $secrets_dir/$secret_name; refusing to rotate either value"
            return 1
        fi

        mode=$(_secret_file_mode "$secrets_dir/$secret_name")
        if [ "$mode" != "600" ]; then
            log_error "Grafana secret file must have mode 600: $secrets_dir/$secret_name (found $mode)"
            return 1
        fi
    done

    return 0
}

ensure_grafana_runtime_secrets() {
    local env_file="$1"
    local secrets_dir="${2:-${INSTALL_DIR:-/opt/bisq-support}/secrets}"
    local entry env_name secret_name secret_file env_value file_value selected_value
    local entries=(
        "GRAFANA_ADMIN_PASSWORD:grafana_admin_password"
        "GRAFANA_DATASOURCE_API_KEY:grafana_datasource_api_key"
    )

    if ! command -v openssl >/dev/null 2>&1; then
        log_error "openssl is required to provision Grafana runtime secrets"
        return 1
    fi

    mkdir -p "$(dirname "$env_file")" "$secrets_dir"
    chmod 700 "$secrets_dir"
    touch "$env_file"
    chmod 600 "$env_file"

    # Detect conflicts before writing either secret, so the operation fails
    # without partially reconciling a mismatched legacy installation.
    for entry in "${entries[@]}"; do
        env_name="${entry%%:*}"
        secret_name="${entry#*:}"
        secret_file="$secrets_dir/$secret_name"
        env_value=$(_read_env_value "$env_file" "$env_name")
        file_value=""
        if [ -s "$secret_file" ]; then
            file_value=$(cat "$secret_file")
        fi

        if [ -n "$env_value" ] && [ -n "$file_value" ] && [ "$env_value" != "$file_value" ]; then
            log_error "$env_name differs from $secret_file; refusing to rotate either value"
            return 1
        fi
    done

    for entry in "${entries[@]}"; do
        env_name="${entry%%:*}"
        secret_name="${entry#*:}"
        secret_file="$secrets_dir/$secret_name"
        env_value=$(_read_env_value "$env_file" "$env_name")
        file_value=""
        if [ -s "$secret_file" ]; then
            file_value=$(cat "$secret_file")
        fi

        if [ -n "$env_value" ]; then
            selected_value="$env_value"
        elif [ -n "$file_value" ]; then
            selected_value="$file_value"
        else
            selected_value=$(openssl rand -base64 32 | tr -d '\n')
            if [ -z "$selected_value" ]; then
                log_error "Failed to generate $env_name"
                return 1
            fi
        fi

        if [ ! -s "$secret_file" ]; then
            local secret_tmp
            secret_tmp=$(mktemp "${secret_file}.tmp.XXXXXX") || return 1
            chmod 600 "$secret_tmp"
            printf '%s\n' "$selected_value" > "$secret_tmp"
            mv "$secret_tmp" "$secret_file"
        fi
        chmod 600 "$secret_file"

        if ! _write_env_value "$env_file" "$env_name" "$selected_value"; then
            log_error "Failed to write $env_name to $env_file"
            return 1
        fi
    done

    validate_grafana_runtime_secrets "$env_file" "$secrets_dir"
}

validate_runtime_configuration() {
    # Reads from env file if given, otherwise falls back to shell env.
    local env_file="${1:-}"
    local _rc_cache=""

    # Read entire file once to avoid per-var grep forks
    if [ -n "$env_file" ] && [ -f "$env_file" ]; then
        _rc_cache=$(cat "$env_file")
    fi

    _env_val() {
        local var="$1" default="${2:-}"
        if [ -n "$_rc_cache" ]; then
            local val
            val=$(echo "$_rc_cache" | grep -E "^${var}=" | head -1 | sed "s/^[^=]*=//" || true)
            echo "${val:-$default}"
        else
            eval "echo \"\${${var}:-${default}}\""
        fi
    }

    if is_env_enabled "$(_env_val TRUST_MONITOR_ENABLED false)" && [ -z "$(_env_val TRUST_MONITOR_ACTOR_KEY_SECRET)" ]; then
        log_error "TRUST_MONITOR_ACTOR_KEY_SECRET is required when TRUST_MONITOR_ENABLED=true"
        return 1
    fi

    if is_env_enabled "$(_env_val MATRIX_CHATOPS_ENABLED false)" && [ -z "$(_env_val MATRIX_CHATOPS_ROOM_IDS)" ]; then
        log_error "MATRIX_CHATOPS_ROOM_IDS is required when MATRIX_CHATOPS_ENABLED=true"
        return 1
    fi

    if is_env_enabled "$(_env_val BISQ2_CHATOPS_ENABLED false)" && [ -z "$(_env_val BISQ2_CHATOPS_CHANNEL_IDS)" ]; then
        log_error "BISQ2_CHATOPS_CHANNEL_IDS is required when BISQ2_CHATOPS_ENABLED=true"
        return 1
    fi

    unset -f _env_val
    return 0
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
    # Expanding the validated function name now is intentional.
    # shellcheck disable=SC2064
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
export -f source_deploy_paths
export -f validate_app_env
export -f detect_env_shadowing
export -f is_env_enabled
export -f uses_qdrant_runtime
export -f _read_env_value
export -f _write_env_value
export -f _secret_file_mode
export -f validate_grafana_runtime_secrets
export -f ensure_grafana_runtime_secrets
export -f validate_runtime_configuration
export -f display_banner
export -f get_container_name
export -f validate_git_repo
export -f init_common_env
export -f setup_cleanup_trap

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

acquire_production_lifecycle_lock() {
    local install_dir="$1"
    local canonical_install_dir=""
    local control_dir=""
    local lock_file=""
    local failure_marker=""
    local lock_state=""

    if ! command -v flock >/dev/null 2>&1; then
        log_error "flock is required for production lifecycle coordination" >&2
        return 1
    fi

    if [ -n "${BISQ_SUPPORT_LIFECYCLE_LOCK_FD:-}" ]; then
        if [[ "$BISQ_SUPPORT_LIFECYCLE_LOCK_FD" =~ ^[0-9]+$ ]] \
            && [ -e "/dev/fd/$BISQ_SUPPORT_LIFECYCLE_LOCK_FD" ]; then
            return 0
        fi
        log_error "Inherited production lifecycle lock is invalid" >&2
        return 1
    fi
    canonical_install_dir=$(cd "$install_dir" 2>/dev/null && pwd -P) || {
        log_error "Production installation directory is unavailable" >&2
        return 1
    }
    if [ -L "$canonical_install_dir/failed_updates" ]; then
        log_error "Production lifecycle control directory is unsafe" >&2
        return 1
    fi
    mkdir -p "$canonical_install_dir/failed_updates" || return 1
    control_dir="$canonical_install_dir/failed_updates/disaster-recovery"
    if [ -L "$control_dir" ]; then
        log_error "Production lifecycle control directory is unsafe" >&2
        return 1
    fi
    mkdir -p "$control_dir" || return 1
    chmod 700 "$control_dir" || return 1
    lock_file="$control_dir/recovery.lock"
    failure_marker="$control_dir/recovery-blocked"
    if [ -e "$failure_marker" ] || [ -L "$failure_marker" ]; then
        log_error "Production recovery is blocked; refusing a lifecycle change" >&2
        return 1
    fi
    if [ -L "$lock_file" ] \
        || { [ -e "$lock_file" ] && [ ! -f "$lock_file" ]; }; then
        log_error "Production lifecycle lock path is unsafe" >&2
        return 1
    fi
    umask 077
    BISQ_SUPPORT_LIFECYCLE_LOCK_FD=202
    if ! exec 202<>"$lock_file"; then
        log_error "Could not open the production lifecycle lock" >&2
        return 1
    fi
    export BISQ_SUPPORT_LIFECYCLE_LOCK_FD
    chmod 600 "$lock_file" || return 1
    if ! flock -n "$BISQ_SUPPORT_LIFECYCLE_LOCK_FD"; then
        log_error "Another production lifecycle operation is active" >&2
        exec 202>&-
        unset BISQ_SUPPORT_LIFECYCLE_LOCK_FD
        return 1
    fi
    IFS= read -r lock_state < "$lock_file" || true
    if [ "$lock_state" = blocked ]; then
        log_error "Production recovery is blocked; refusing a lifecycle change" >&2
        flock -u "$BISQ_SUPPORT_LIFECYCLE_LOCK_FD" || true
        exec 202>&-
        unset BISQ_SUPPORT_LIFECYCLE_LOCK_FD
        return 1
    fi
}

_validate_compose_container_mode() {
    case "$1" in
        existing|running)
            return 0
            ;;
        *)
            log_error "Compose container state mode is invalid" >&2
            return 1
            ;;
    esac
}

_normalize_container_ids() {
    local container_output="$1"
    local container_id=""
    local normalized=""

    while IFS= read -r container_id; do
        [ -n "$container_id" ] || continue
        if [[ ! "$container_id" =~ ^[0-9a-f]{12,64}$ ]]; then
            log_error "Existing production Compose container has an invalid identity" >&2
            return 1
        fi
        normalized+="$container_id"$'\n'
    done <<< "$container_output"
    [ -n "$normalized" ] || return 0
    printf '%s' "$normalized" | LC_ALL=C sort
}

_existing_api_container_for_docker_dir() {
    local docker_dir="$1"
    local mode="${2:-existing}"
    local canonical_docker_dir=""
    local container_output=""
    local container_id=""
    local candidate_id=""
    local metadata=""
    local project_name=""
    local working_dir=""
    local service_name=""
    local oneoff=""
    local container_state=""
    local extra_metadata=""
    local canonical_working_dir=""
    local container_ids=()

    _validate_compose_container_mode "$mode" || return 1
    canonical_docker_dir=$(cd "$docker_dir" 2>/dev/null && pwd -P) || {
        log_error "Existing production Docker directory is unavailable" >&2
        return 1
    }
    if ! container_output=$(docker ps --all --no-trunc --quiet \
        --filter label=com.docker.compose.service=api \
        --filter "label=com.docker.compose.project.working_dir=$canonical_docker_dir"); then
        log_error "Could not inspect the existing production Compose stack" >&2
        return 1
    fi
    while IFS= read -r candidate_id; do
        [ -n "$candidate_id" ] && container_ids+=("$candidate_id")
    done <<< "$container_output"
    if [ "${#container_ids[@]}" -ne 1 ]; then
        log_error \
            "Exactly one API container must belong to the existing production Docker directory" >&2
        return 1
    fi
    container_id="${container_ids[0]}"
    if [[ ! "$container_id" =~ ^[0-9a-f]{12,64}$ ]]; then
        log_error "Existing production API container has an invalid identity" >&2
        return 1
    fi
    if ! metadata=$(docker inspect --format \
        '{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.project.working_dir"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{index .Config.Labels "com.docker.compose.oneoff"}}|{{.State.Status}}' \
        "$container_id"); then
        log_error "Could not inspect the existing production API container" >&2
        return 1
    fi
    IFS='|' read -r project_name working_dir service_name oneoff \
        container_state extra_metadata <<< "$metadata"
    if [[ ! "$project_name" =~ ^[a-z0-9][a-z0-9_-]*$ ]] \
        || [ "$service_name" != api ] \
        || { [ "$oneoff" != False ] && [ "$oneoff" != false ]; } \
        || [ -n "$extra_metadata" ]; then
        log_error "Existing production API container has invalid Compose identity" >&2
        return 1
    fi
    canonical_working_dir=$(cd "$working_dir" 2>/dev/null && pwd -P) || {
        log_error \
            "Existing production API container has an unavailable Compose working directory" >&2
        return 1
    }
    if [ "$canonical_working_dir" != "$canonical_docker_dir" ]; then
        log_error \
            "Existing production API container belongs to a different Compose working directory" >&2
        return 1
    fi
    if [ "$mode" = running ]; then
        if [ "$container_state" != running ]; then
            log_error "Existing production API container is not running" >&2
            return 1
        fi
    else
        case "$container_state" in
            created|exited|running)
                ;;
            *)
                log_error "Existing production API container is not recoverable" >&2
                return 1
                ;;
        esac
    fi
    printf '%s\n' "$container_id"
}

resolve_existing_compose_project() {
    local docker_dir="$1"
    local mode="${2:-existing}"
    local container_id=""
    local project_name=""

    container_id=$(_existing_api_container_for_docker_dir "$docker_dir" "$mode") \
        || return 1
    if ! project_name=$(docker inspect --format \
        '{{index .Config.Labels "com.docker.compose.project"}}' \
        "$container_id"); then
        log_error "Could not resolve the existing production Compose project" >&2
        return 1
    fi
    if [[ ! "$project_name" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
        log_error "Existing production Compose project has an invalid identity" >&2
        return 1
    fi
    printf '%s\n' "$project_name"
}

_strict_compose_env_assignment() {
    local env_file="$1"
    local key="$2"
    local allow_empty="${3:-false}"
    local assignment_state=""
    local assignment_count=""
    local canonical_count=""
    local assignment_value=""
    local extra_state=""

    if [ ! -f "$env_file" ] || [[ ! "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]]; then
        log_error "Protected Compose setting could not be inspected" >&2
        return 1
    fi
    assignment_state=$(awk -v key="$key" '
        {
            raw = $0
            normalized = $0
            sub(/^[[:space:]]+/, "", normalized)
            if (normalized ~ /^export[[:space:]]+/) {
                sub(/^export[[:space:]]+/, "", normalized)
            }
            if (normalized ~ ("^" key "([[:space:]]*=|[[:space:]]*$)")) {
                assignments++
                if (index(raw, key "=") == 1) {
                    canonical++
                    value = substr(raw, length(key) + 2)
                }
            }
        }
        END {
            printf "%d|%d|%s\n", assignments + 0, canonical + 0, value
        }
    ' "$env_file") || {
        log_error "Protected Compose setting could not be parsed" >&2
        return 1
    }
    IFS='|' read -r assignment_count canonical_count assignment_value \
        extra_state <<< "$assignment_state"
    if [ "$assignment_count" -eq 0 ] \
        && [ "$canonical_count" -eq 0 ] \
        && [ -z "$assignment_value" ] \
        && [ -z "$extra_state" ]; then
        return 3
    fi
    if [ "$assignment_count" -ne 1 ] \
        || [ "$canonical_count" -ne 1 ] \
        || { [ -z "$assignment_value" ] && [ "$allow_empty" != true ]; } \
        || [ -n "$extra_state" ]; then
        log_error "Protected Compose setting must use one canonical assignment" >&2
        return 1
    fi
    printf '%s\n' "$assignment_value"
}

_persisted_compose_project() {
    local docker_dir="$1"
    local env_file="$docker_dir/.env"
    local project_name=""
    local status=0

    [ -f "$env_file" ] || return 0
    [ ! -L "$env_file" ] || {
        log_error "Protected production Compose configuration must not be a symlink" >&2
        return 1
    }
    if project_name=$(_strict_compose_env_assignment \
        "$env_file" COMPOSE_PROJECT_NAME); then
        :
    else
        status=$?
        [ "$status" -eq 3 ] && return 0
        return "$status"
    fi
    if [[ ! "$project_name" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
        log_error "Persisted Compose project setting is invalid" >&2
        return 1
    fi
    printf '%s\n' "$project_name"
}

_canonical_compose_container_ids() {
    local docker_dir="$1"
    local compose_file="${2:-docker-compose.yml}"
    local canonical_docker_dir=""
    local compose_output=""
    local project_output=""
    local working_dir_output=""
    local compose_ids=""
    local project_ids=""
    local working_dir_ids=""
    local container_id=""
    local metadata=""
    local project_name=""
    local working_dir=""
    local service_name=""
    local container_number=""
    local oneoff=""
    local container_state=""
    local extra_metadata=""
    local canonical_working_dir=""
    local service_names=""
    local sorted_services=""
    local previous_service=""

    if [[ ! "${COMPOSE_PROJECT_NAME:-}" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
        log_error "Compose project must be pinned before inspecting the stack" >&2
        return 1
    fi
    canonical_docker_dir=$(cd "$docker_dir" 2>/dev/null && pwd -P) || {
        log_error "Existing production Docker directory is unavailable" >&2
        return 1
    }
    if ! compose_output=$(run_docker_compose "$docker_dir" "$compose_file" \
        ps --all --orphans=false --no-trunc -q); then
        log_error "Could not enumerate canonical production Compose containers" >&2
        return 1
    fi
    if ! project_output=$(docker ps --all --no-trunc --quiet \
        --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME"); then
        log_error "Could not enumerate containers for the production Compose project" >&2
        return 1
    fi
    if ! working_dir_output=$(docker ps --all --no-trunc --quiet \
        --filter "label=com.docker.compose.project.working_dir=$canonical_docker_dir"); then
        log_error "Could not enumerate containers for the production Docker directory" >&2
        return 1
    fi
    compose_ids=$(_normalize_container_ids "$compose_output") || return 1
    project_ids=$(_normalize_container_ids "$project_output") || return 1
    working_dir_ids=$(_normalize_container_ids "$working_dir_output") || return 1
    if [ -z "$compose_ids" ] \
        || [ "$compose_ids" != "$project_ids" ] \
        || [ "$compose_ids" != "$working_dir_ids" ]; then
        log_error \
            "Existing production Compose stack contains ambiguous or stale containers" >&2
        return 1
    fi

    while IFS= read -r container_id; do
        [ -n "$container_id" ] || continue
        if ! metadata=$(docker inspect --format \
            '{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.project.working_dir"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{index .Config.Labels "com.docker.compose.container-number"}}|{{index .Config.Labels "com.docker.compose.oneoff"}}|{{.State.Status}}' \
            "$container_id"); then
            log_error "Could not inspect a production Compose container" >&2
            return 1
        fi
        IFS='|' read -r project_name working_dir service_name container_number \
            oneoff container_state extra_metadata <<< "$metadata"
        canonical_working_dir=$(cd "$working_dir" 2>/dev/null && pwd -P) || {
            log_error "Production Compose container working directory is unavailable" >&2
            return 1
        }
        if [ "$project_name" != "$COMPOSE_PROJECT_NAME" ] \
            || [ "$canonical_working_dir" != "$canonical_docker_dir" ] \
            || [[ ! "$service_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] \
            || [[ ! "$container_number" =~ ^[1-9][0-9]*$ ]] \
            || { [ "$oneoff" != False ] && [ "$oneoff" != false ]; } \
            || [ -n "$extra_metadata" ]; then
            log_error "Production Compose container metadata is invalid" >&2
            return 1
        fi
        case "$container_state" in
            created|exited|running)
                ;;
            *)
                log_error "Production Compose container is not recoverable" >&2
                return 1
                ;;
        esac
        service_names+="$service_name"$'\n'
    done <<< "$compose_ids"
    sorted_services=$(printf '%s' "$service_names" | LC_ALL=C sort) || return 1
    while IFS= read -r service_name; do
        [ -n "$service_name" ] || continue
        if [ "$service_name" = "$previous_service" ]; then
            log_error "Production Compose service has multiple containers" >&2
            return 1
        fi
        previous_service="$service_name"
    done <<< "$sorted_services"
    printf '%s\n' "$compose_ids"
}

pin_existing_compose_project() {
    local docker_dir="$1"
    local compose_file="${2:-docker-compose.yml}"
    local mode="${3:-existing}"
    local resolved_project=""
    local persisted_project=""

    resolved_project=$(resolve_existing_compose_project "$docker_dir" "$mode") \
        || return 1
    persisted_project=$(_persisted_compose_project "$docker_dir") || return 1
    if { [ -n "${COMPOSE_PROJECT_NAME:-}" ] \
            && [ "$COMPOSE_PROJECT_NAME" != "$resolved_project" ]; } \
        || { [ -n "$persisted_project" ] \
            && [ "$persisted_project" != "$resolved_project" ]; }; then
        log_error \
            "Configured Compose project does not match the existing production stack" >&2
        return 1
    fi
    export COMPOSE_PROJECT_NAME="$resolved_project"
    _canonical_compose_container_ids "$docker_dir" "$compose_file" >/dev/null
}

pin_configured_or_existing_compose_project() {
    local docker_dir="$1"
    local compose_file="${2:-docker-compose.yml}"
    local canonical_docker_dir=""
    local persisted_project=""
    local container_output=""
    local project_output=""

    canonical_docker_dir=$(cd "$docker_dir" 2>/dev/null && pwd -P) || {
        log_error "Existing production Docker directory is unavailable" >&2
        return 1
    }
    if ! container_output=$(docker ps --all --no-trunc --quiet \
        --filter "label=com.docker.compose.project.working_dir=$canonical_docker_dir"); then
        log_error "Could not inspect the existing production Compose stack" >&2
        return 1
    fi
    if [ -n "$container_output" ]; then
        pin_existing_compose_project "$docker_dir" "$compose_file" existing \
            || return 1
        persist_compose_project_name "$docker_dir"
        return $?
    fi

    persisted_project=$(_persisted_compose_project "$docker_dir") || return 1
    if [[ ! "$persisted_project" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
        log_error "A persisted Compose project is required to start this stack" >&2
        return 1
    fi
    if [ -n "${COMPOSE_PROJECT_NAME:-}" ] \
        && [ "$COMPOSE_PROJECT_NAME" != "$persisted_project" ]; then
        log_error "Configured Compose project conflicts with protected state" >&2
        return 1
    fi
    if ! project_output=$(docker ps --all --no-trunc --quiet \
        --filter "label=com.docker.compose.project=$persisted_project"); then
        log_error "Could not inspect the persisted production Compose project" >&2
        return 1
    fi
    if [ -n "$project_output" ]; then
        log_error \
            "Persisted Compose project is occupied by a different working directory" >&2
        return 1
    fi
    export COMPOSE_PROJECT_NAME="$persisted_project"
    return 0
}

persist_compose_project_name() {
    local docker_dir="$1"
    local env_file="$docker_dir/.env"
    local persisted_project=""
    local temporary_file=""

    if [[ ! "${COMPOSE_PROJECT_NAME:-}" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
        log_error "Compose project must be pinned before it can be persisted" >&2
        return 1
    fi
    if [ ! -f "$env_file" ] || [ -L "$env_file" ]; then
        log_error "Protected production Compose configuration is unavailable" >&2
        return 1
    fi
    persisted_project=$(_persisted_compose_project "$docker_dir") || return 1
    if [ -n "$persisted_project" ]; then
        if [ "$persisted_project" != "$COMPOSE_PROJECT_NAME" ]; then
            log_error "Persisted Compose project conflicts with the existing stack" >&2
            return 1
        fi
        return 0
    fi
    temporary_file=$(mktemp "$docker_dir/.env.compose-project.XXXXXXXX") || {
        log_error "Could not stage the protected Compose project setting" >&2
        return 1
    }
    if ! cp -p -- "$env_file" "$temporary_file" \
        || ! printf '\nCOMPOSE_PROJECT_NAME=%s\n' "$COMPOSE_PROJECT_NAME" \
            >> "$temporary_file" \
        || ! mv -- "$temporary_file" "$env_file"; then
        rm -f -- "$temporary_file"
        log_error "Could not persist the protected Compose project setting" >&2
        return 1
    fi
    persisted_project=$(_persisted_compose_project "$docker_dir") || return 1
    if [ "$persisted_project" != "$COMPOSE_PROJECT_NAME" ]; then
        log_error "Protected Compose project setting failed verification" >&2
        return 1
    fi
}

validate_existing_api_data_identity() {
    local docker_dir="$1"
    local compose_file="$2"
    local expected_data_dir="$3"
    local mode="${4:-existing}"
    local container_id=""
    local container_project=""
    local env_entries=""
    local mount_entry=""
    local mount_type=""
    local mount_source=""
    local extra_mount=""
    local canonical_source=""
    local canonical_expected_source=""

    if [[ ! "${COMPOSE_PROJECT_NAME:-}" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
        log_error "Compose project must be pinned before validating application data" >&2
        return 1
    fi
    container_id=$(_existing_api_container_for_docker_dir "$docker_dir" "$mode") \
        || return 1
    if ! container_project=$(docker inspect --format \
        '{{index .Config.Labels "com.docker.compose.project"}}' \
        "$container_id"); then
        log_error "Could not revalidate the existing production API project" >&2
        return 1
    fi
    if [ "$container_project" != "$COMPOSE_PROJECT_NAME" ]; then
        log_error "Existing production API belongs to a different Compose project" >&2
        return 1
    fi
    if ! env_entries=$(docker inspect --format \
        '{{range .Config.Env}}{{if eq (index (split . "=") 0) "DATA_DIR"}}{{println .}}{{end}}{{end}}' \
        "$container_id"); then
        log_error "Could not inspect the existing production API data setting" >&2
        return 1
    fi
    if [ "$env_entries" != DATA_DIR=/data ]; then
        log_error "Existing production API must use exactly DATA_DIR=/data" >&2
        return 1
    fi
    if ! mount_entry=$(docker inspect --format \
        '{{range .Mounts}}{{if eq .Destination "/data"}}{{printf "%s|%s\n" .Type .Source}}{{end}}{{end}}' \
        "$container_id"); then
        log_error "Could not inspect the existing production API data mount" >&2
        return 1
    fi
    IFS='|' read -r mount_type mount_source extra_mount <<< "$mount_entry"
    if [ "$mount_type" != bind ] \
        || [ -z "$mount_source" ] \
        || [ -n "$extra_mount" ] \
        || [[ "$mount_entry" == *$'\n'* ]]; then
        log_error "Existing production API data mount has invalid identity" >&2
        return 1
    fi
    canonical_source=$(cd "$mount_source" 2>/dev/null && pwd -P) || {
        log_error "Existing production API data source is unavailable" >&2
        return 1
    }
    canonical_expected_source=$(cd "$expected_data_dir" 2>/dev/null && pwd -P) || {
        log_error "Existing production application data directory is unavailable" >&2
        return 1
    }
    if [ "$canonical_source" != "$canonical_expected_source" ]; then
        log_error \
            "Existing production API data mount does not use the existing application data" >&2
        return 1
    fi
}

validate_compose_loopback_http_binding() {
    local docker_dir="$1"
    local compose_file="${2:-docker-compose.yml}"
    local nginx_container=""
    local binding=""
    local container_port=""
    local host_ip=""
    local host_port=""
    local extra_binding=""

    if [[ ! "${COMPOSE_PROJECT_NAME:-}" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
        log_error "Compose project must be pinned before validating HTTP exposure" >&2
        return 1
    fi
    if ! nginx_container=$(run_docker_compose "$docker_dir" "$compose_file" \
        ps --all --orphans=false --no-trunc -q nginx); then
        log_error "Could not inspect the production nginx container" >&2
        return 1
    fi
    if [[ ! "$nginx_container" =~ ^[0-9a-f]{12,64}$ ]]; then
        log_error "Production Compose must resolve exactly one nginx container" >&2
        return 1
    fi
    if ! binding=$(docker inspect --format \
        '{{range $port, $bindings := .HostConfig.PortBindings}}{{range $bindings}}{{printf "%s|%s|%s\n" $port .HostIp .HostPort}}{{end}}{{end}}' \
        "$nginx_container"); then
        log_error "Could not inspect the production HTTP binding" >&2
        return 1
    fi
    IFS='|' read -r container_port host_ip host_port extra_binding <<< "$binding"
    if [ "$container_port" != 80/tcp ] \
        || [ "$host_ip" != 127.0.0.1 ] \
        || [[ ! "$host_port" =~ ^[1-9][0-9]{0,4}$ ]] \
        || [ "$host_port" -gt 65535 ] \
        || [ -n "$extra_binding" ] \
        || [[ "$binding" == *$'\n'* ]]; then
        log_error "Production HTTP listener must be bound only to loopback" >&2
        return 1
    fi
}

validate_api_runtime_false_settings() {
    local docker_dir="$1"
    shift
    local api_container=""
    local container_project=""
    local setting=""
    local setting_entries=""

    if [ "$#" -eq 0 ]; then
        log_error "At least one protected API runtime setting is required" >&2
        return 1
    fi
    if [[ ! "${COMPOSE_PROJECT_NAME:-}" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
        log_error "Compose project must be pinned before validating API runtime" >&2
        return 1
    fi
    api_container=$(_existing_api_container_for_docker_dir \
        "$docker_dir" running) || return 1
    if ! container_project=$(docker inspect --format \
        '{{index .Config.Labels "com.docker.compose.project"}}' \
        "$api_container"); then
        log_error "Could not revalidate the production API project" >&2
        return 1
    fi
    if [ "$container_project" != "$COMPOSE_PROJECT_NAME" ]; then
        log_error "Production API belongs to a different Compose project" >&2
        return 1
    fi
    for setting in "$@"; do
        if [[ ! "$setting" =~ ^[A-Z_][A-Z0-9_]*$ ]]; then
            log_error "Protected API runtime setting name is invalid" >&2
            return 1
        fi
        if ! setting_entries=$(docker inspect --format \
            "{{range .Config.Env}}{{if eq (index (split . \"=\") 0) \"$setting\"}}{{println .}}{{end}}{{end}}" \
            "$api_container"); then
            log_error "Could not inspect a protected production API setting" >&2
            return 1
        fi
        if [ "$setting_entries" != "$setting=false" ]; then
            log_error "$setting must be exactly false in the production API" >&2
            return 1
        fi
    done
}

validate_api_http_cookie_mode() {
    local docker_dir="$1"
    validate_api_runtime_false_settings "$docker_dir" COOKIE_SECURE || {
        log_error "Production HTTP testing requires exactly COOKIE_SECURE=false" >&2
        return 1
    }
}

capture_compose_persistent_mounts() {
    local docker_dir="$1"
    local compose_file="${2:-docker-compose.yml}"
    local canonical_ids=""
    local container_id=""
    local inspect_output=""
    local mount_map=""
    local sorted_mount_map=""
    local persistent_mount_map=""
    local mount_record=""
    local service_name=""
    local destination=""
    local mount_type=""
    local mount_source=""
    local extra_mount=""
    local mount_key=""
    local previous_key=""

    canonical_ids=$(_canonical_compose_container_ids \
        "$docker_dir" "$compose_file") || return 1
    while IFS= read -r container_id; do
        [ -n "$container_id" ] || continue
        if ! inspect_output=$(docker inspect --format \
            '{{$service := index .Config.Labels "com.docker.compose.service"}}{{range .Mounts}}{{if eq .Type "bind"}}{{printf "%s|%s|bind|%s\n" $service .Destination .Source}}{{else if eq .Type "volume"}}{{printf "%s|%s|volume|%s\n" $service .Destination .Name}}{{end}}{{end}}' \
            "$container_id"); then
            log_error "Could not inspect existing production persistent mounts" >&2
            return 1
        fi
        [ -z "$inspect_output" ] || mount_map+="$inspect_output"$'\n'
    done <<< "$canonical_ids"
    if [ -z "$mount_map" ]; then
        log_error "Existing production Compose stack has no persistent mount identity" >&2
        return 1
    fi
    sorted_mount_map=$(printf '%s' "$mount_map" | LC_ALL=C sort) || return 1
    while IFS= read -r mount_record; do
        [ -n "$mount_record" ] || continue
        IFS='|' read -r service_name destination mount_type mount_source \
            extra_mount <<< "$mount_record"
        if [[ ! "$service_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] \
            || [[ "$destination" != /* ]] \
            || [ -z "$mount_source" ] \
            || [ -n "$extra_mount" ]; then
            log_error "Production persistent mount metadata is invalid" >&2
            return 1
        fi
        case "$mount_type" in
            bind)
                case "$destination" in
                    /data|/var/log|/var/log/*)
                        ;;
                    *)
                        # Source, configuration, secrets, and host telemetry
                        # binds are not persistent application state. They may
                        # be deliberately removed or replaced by an update.
                        continue
                        ;;
                esac
                [[ "$mount_source" == /* ]] || {
                    log_error "Production bind mount identity is invalid" >&2
                    return 1
                }
                ;;
            volume)
                [[ "$mount_source" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || {
                    log_error "Production volume identity is invalid" >&2
                    return 1
                }
                ;;
            *)
                log_error "Production persistent mount type is invalid" >&2
                return 1
                ;;
        esac
        mount_key="$service_name|$destination"
        if [ "$mount_key" = "$previous_key" ]; then
            log_error "Production Compose mount identity is duplicated" >&2
            return 1
        fi
        previous_key="$mount_key"
        persistent_mount_map+="$mount_record"$'\n'
    done <<< "$sorted_mount_map"
    if [ -z "$persistent_mount_map" ]; then
        log_error "Existing production Compose stack has no persistent state mounts" >&2
        return 1
    fi
    printf '%s' "$persistent_mount_map"
}

_effective_compose_env_value() {
    local docker_dir="$1"
    local key="$2"
    local env_file="$docker_dir/.env"

    # Exported values take precedence over Compose's project .env file.
    if printenv "$key" >/dev/null 2>&1; then
        printenv "$key"
        return 0
    fi

    local value=""
    local status=0
    [ -f "$env_file" ] || return 0
    if value=$(_strict_compose_env_assignment "$env_file" "$key" true); then
        printf '%s\n' "$value"
        return 0
    else
        status=$?
    fi
    [ "$status" -eq 3 ] && return 0
    return "$status"
}

validate_base_compose_exposure() {
    local docker_dir="$1"
    local setting
    local value

    # A missing deploy.env must not turn a selected clearnet TLS deployment
    # into base-only HTTP. Refuse every TLS-only input while no overlay is
    # selected, regardless of whether it came from the shell or docker/.env.
    for setting in \
        NGINX_HTTPS_BIND_ADDRESS \
        NGINX_TLS_CERTIFICATE_DIR \
        NGINX_TLS_CERTIFICATE_FILENAME \
        NGINX_TLS_PRIVATE_KEY_FILENAME; do
        value=$(_effective_compose_env_value "$docker_dir" "$setting") \
            || return 1
        if [ -n "$value" ]; then
            log_error \
                "Base Compose mode conflicts with clearnet TLS settings; restore the reviewed deploy selection" >&2
            return 1
        fi
    done

    value=$(_effective_compose_env_value \
        "$docker_dir" NGINX_TLS_REDIRECT_HTTP) || return 1
    if is_env_enabled "$value"; then
        log_error \
            "Base Compose mode cannot enable HTTPS redirection; restore the reviewed deploy selection" >&2
        return 1
    fi

    value=$(_effective_compose_env_value \
        "$docker_dir" NGINX_HTTP_BIND_ADDRESS) || return 1
    case "$value" in
        ""|127.0.0.1)
            ;;
        *)
            log_error \
                "Base Compose mode requires the loopback HTTP bind; restore the reviewed deploy selection" >&2
            return 1
            ;;
    esac

    return 0
}

# Only the reviewed production TLS overlay may be persisted in deploy.env.
# Keeping this allowlist here prevents deploy-path configuration from loading
# arbitrary Compose files with host mounts or privileged service definitions.
validate_compose_override_file() {
    local docker_dir="${1:-${DOCKER_DIR:-}}"
    local override_file="${BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE:-}"

    if [ -z "$override_file" ]; then
        validate_base_compose_exposure "$docker_dir"
        return $?
    fi

    if [ "$override_file" != "docker-compose.tls.yml" ]; then
        log_error \
            "BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE must be empty or docker-compose.tls.yml" >&2
        return 1
    fi

    if [ -z "$docker_dir" ] || [ ! -f "$docker_dir/$override_file" ]; then
        log_error \
            "Configured Compose override is unavailable in the Docker directory" >&2
        return 1
    fi

    return 0
}

# Run every production Compose action with the persisted, validated overlay.
# With no configured override this is exactly equivalent to the legacy
# `docker compose -f docker-compose.yml ...` invocation.
run_docker_compose() {
    local docker_dir="$1"
    local compose_file="$2"
    shift 2

    if ! validate_compose_override_file "$docker_dir"; then
        return 1
    fi

    local compose_args=()
    if [ -n "${COMPOSE_PROJECT_NAME:-}" ]; then
        if [[ ! "$COMPOSE_PROJECT_NAME" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
            log_error "COMPOSE_PROJECT_NAME has an invalid value" >&2
            return 1
        fi
        compose_args+=(--project-name "$COMPOSE_PROJECT_NAME")
    fi
    compose_args+=(-f "$compose_file")
    if [ -n "${BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE:-}" ]; then
        compose_args+=(-f "$BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE")
    fi

    (
        cd "$docker_dir" || return 1
        docker compose "${compose_args[@]}" "$@"
    )
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
# deploy.env  → allowlisted deploy settings (repo/install paths, TLS overlay)
# docker/.env → ALL app config (secrets, room IDs, feature flags)
#
# Docker Compose reads docker/.env automatically. Scripts source deploy.env
# only for the handful of shell-only settings that Docker doesn't need.
# ---------------------------------------------------------------------------

# Allowed deployment setting names.
# Everything else in deploy.env is considered app config (a shadowing risk).
_DEPLOY_PATH_VARS="BISQ_SUPPORT_INSTALL_DIR|BISQ_SUPPORT_REPO_URL|BISQ_SUPPORT_SECRETS_DIR|BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE|BISQ2_INSTALL_DIR|BISQ2_REPO_URL"

# Source ONLY allowlisted deployment settings from deploy.env.
# App config vars are ignored so they cannot shadow docker/.env values.
source_deploy_paths() {
    local env_file="${1:-/etc/bisq-support/deploy.env}"

    if [ ! -f "$env_file" ]; then
        log_warning "Deploy paths file $env_file not found."
        return 1
    fi

    log_info "Sourcing deployment settings from $env_file"

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
export -f acquire_production_lifecycle_lock
export -f _validate_compose_container_mode
export -f _normalize_container_ids
export -f _existing_api_container_for_docker_dir
export -f resolve_existing_compose_project
export -f _strict_compose_env_assignment
export -f _persisted_compose_project
export -f _canonical_compose_container_ids
export -f pin_existing_compose_project
export -f pin_configured_or_existing_compose_project
export -f persist_compose_project_name
export -f validate_existing_api_data_identity
export -f validate_compose_loopback_http_binding
export -f validate_api_runtime_false_settings
export -f validate_api_http_cookie_mode
export -f capture_compose_persistent_mounts
export -f validate_compose_override_file
export -f run_docker_compose
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

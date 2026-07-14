#!/bin/bash
# Docker and service management utilities for Bisq Support Assistant

# Source common functions
LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck disable=SC1091
source "$LIB_DIR/common.sh"

# Configuration
# Health check configuration for service startup verification
# bisq2-api needs longer timeout due to Java startup + Bisq network initialization (typically 60-180s)
# Formula: Initial wait (15s in update.sh) + (RETRIES × INTERVAL) should exceed Docker's start_period (120s for bisq2-api)
# Recommended minimum: 180 seconds total = 15s + (90 × 2s) = 195 seconds
HEALTH_CHECK_RETRIES=${HEALTH_CHECK_RETRIES:-90}
HEALTH_CHECK_INTERVAL=${HEALTH_CHECK_INTERVAL:-2}

# Function to check service health using docker compose ps
check_service() {
    local service="$1"
    local docker_dir="${2:-$DOCKER_DIR}"
    local compose_file="${3:-docker-compose.yml}"

    local status
    status=$(run_docker_compose "$docker_dir" "$compose_file" ps --format json "$service" 2>/dev/null)

    if [ -z "$status" ]; then
        log_error "$service: NOT FOUND"
        return 2
    fi

    local state
    local health
    state=$(echo "$status" | jq -r '.State' 2>/dev/null || echo "unknown")
    health=$(echo "$status" | jq -r '.Health' 2>/dev/null || echo "none")

    case "$state" in
        "running")
            if [ "$health" = "healthy" ]; then
                log_success "$service: HEALTHY"
                return 0
            elif [ "$health" = "unhealthy" ]; then
                log_error "$service: UNHEALTHY"
                return 1
            elif [ "$health" = "starting" ]; then
                log_warning "$service: STARTING"
                return 1
            else
                log_success "$service: RUNNING (no health check)"
                return 0
            fi
            ;;
        "exited")
            log_error "$service: EXITED"
            return 1
            ;;
        "restarting")
            log_warning "$service: RESTARTING"
            return 1
            ;;
        *)
            log_warning "$service: $state"
            return 1
            ;;
    esac
}

# Function to wait for service to become healthy
wait_for_healthy() {
    local service="$1"
    local max_wait="${2:-60}"
    local docker_dir="${3:-$DOCKER_DIR}"
    local compose_file="${4:-docker-compose.yml}"
    local waited=0

    log_info "Waiting for $service to become healthy..."

    while [ "$waited" -lt "$max_wait" ]; do
        if check_service "$service" "$docker_dir" "$compose_file" >/dev/null 2>&1; then
            log_success "$service is now healthy"
            return 0
        fi
        sleep 5
        waited=$((waited + 5))
    done

    log_error "$service did not become healthy within ${max_wait}s"
    return 1
}

# Verify that a Compose one-shot service exists and exited successfully.
check_completed_service() {
    local service="$1"
    local docker_dir="${2:-$DOCKER_DIR}"
    local compose_file="${3:-docker-compose.yml}"
    local container_id
    local completion_state
    local state
    local exit_code

    if ! container_id=$(run_docker_compose "$docker_dir" "$compose_file" ps --all -q "$service"); then
        log_error "Failed to inspect one-shot service: $service"
        return 1
    fi

    if [ -z "$container_id" ]; then
        log_error "$service: NOT FOUND"
        return 1
    fi

    if [[ "$container_id" == *$'\n'* ]]; then
        log_error "$service: MULTIPLE CONTAINERS FOUND"
        return 1
    fi

    if ! completion_state=$(docker inspect --format='{{.State.Status}} {{.State.ExitCode}}' "$container_id" 2>/dev/null); then
        log_error "Failed to inspect one-shot container for $service"
        return 1
    fi

    read -r state exit_code <<< "$completion_state"
    if [ "$state" != "exited" ] || [ "$exit_code" != "0" ]; then
        log_error "$service did not complete successfully (state=$state, exit=$exit_code)"
        return 1
    fi

    log_success "$service: COMPLETED"
    return 0
}

# Wait for every long-running Compose service to report healthy while treating
# named one-shot services as completed prerequisites rather than daemons.
wait_for_compose_health() {
    local docker_dir="$1"
    local compose_file="$2"
    local max_wait="$3"
    local wait_interval="$4"
    shift 4

    local -a completed_services=("$@")
    local -a configured_services=()
    local -a long_running_services=()
    local configured_output
    local service
    local completed_service
    local is_completed

    if ! configured_output=$(run_docker_compose "$docker_dir" "$compose_file" config --services); then
        log_error "Failed to list services from the Compose configuration"
        return 1
    fi

    while IFS= read -r service; do
        if [ -n "$service" ]; then
            configured_services+=("$service")
        fi
    done <<< "$configured_output"

    if [ "${#configured_services[@]}" -eq 0 ]; then
        log_error "No services defined in $compose_file"
        return 1
    fi

    for completed_service in "${completed_services[@]}"; do
        is_completed=0
        for service in "${configured_services[@]}"; do
            if [ "$service" = "$completed_service" ]; then
                is_completed=1
                break
            fi
        done
        if [ "$is_completed" -eq 0 ]; then
            log_error "$completed_service is not defined in $compose_file"
            return 1
        fi

        if ! check_completed_service "$completed_service" "$docker_dir" "$compose_file"; then
            return 1
        fi
    done

    for service in "${configured_services[@]}"; do
        is_completed=0
        for completed_service in "${completed_services[@]}"; do
            if [ "$service" = "$completed_service" ]; then
                is_completed=1
                break
            fi
        done
        if [ "$is_completed" -eq 0 ]; then
            long_running_services+=("$service")
        fi
    done

    if [ "${#long_running_services[@]}" -eq 0 ]; then
        log_error "No long-running services defined in $compose_file"
        return 1
    fi

    local elapsed_time=0
    local healthy_output
    local running_output
    local healthy_containers
    local running_containers
    local total_services="${#long_running_services[@]}"

    while [ "$elapsed_time" -lt "$max_wait" ]; do
        if ! healthy_output=$(run_docker_compose "$docker_dir" "$compose_file" ps --filter health=healthy -q "${long_running_services[@]}"); then
            log_error "Failed to inspect Compose service health"
            return 1
        fi

        healthy_containers=0
        if [ -n "$healthy_output" ]; then
            healthy_containers=$(printf '%s\n' "$healthy_output" | wc -l | tr -d '[:space:]')
        fi

        if [ "$healthy_containers" -eq "$total_services" ]; then
            log_success "All $total_services long-running Docker services are healthy"
            return 0
        fi

        if ! running_output=$(run_docker_compose "$docker_dir" "$compose_file" ps --filter status=running -q "${long_running_services[@]}"); then
            log_error "Failed to inspect running Compose services"
            return 1
        fi

        running_containers=0
        if [ -n "$running_output" ]; then
            running_containers=$(printf '%s\n' "$running_output" | wc -l | tr -d '[:space:]')
        fi

        log_warning "Waiting for services ($healthy_containers/$total_services healthy, $running_containers running) [${elapsed_time}s/${max_wait}s]"
        sleep "$wait_interval"
        elapsed_time=$((elapsed_time + wait_interval))
    done

    log_error "Docker services did not become healthy within $max_wait seconds"
    run_docker_compose "$docker_dir" "$compose_file" ps || true
    log_error "Last service logs:"
    run_docker_compose "$docker_dir" "$compose_file" logs --tail=50 || true
    return 1
}

# Function to check container health using docker inspect
check_container_health() {
    local container="$1"
    local retries="$HEALTH_CHECK_RETRIES"

    log_info "Checking health of $container..."

    while [ "$retries" -gt 0 ]; do
        local health_status
        health_status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null)

        if [ "$health_status" = "healthy" ]; then
            log_success "$container is healthy"
            return 0
        fi

        if [ -z "$health_status" ]; then
            # Container may not have health check, check if it's running
            local state
            state=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null)
            if [ "$state" = "running" ]; then
                log_success "$container is running (no health check)"
                return 0
            fi
        fi

        log_warning "Waiting for $container to be healthy. Retries left: $retries"
        sleep "$HEALTH_CHECK_INTERVAL"
        retries=$((retries - 1))
    done

    log_error "Container $container failed health check"
    return 1
}

# Function to restart a service and its dependencies
restart_service_with_deps() {
    local service="$1"
    local docker_dir="${2:-$DOCKER_DIR}"
    local compose_file="${3:-docker-compose.yml}"

    log_info "Restarting $service and dependent services..."

    cd "$docker_dir" || {
        log_error "Failed to change to Docker directory: $docker_dir"
        return 1
    }

    case "$service" in
        "api")
            local api_services=("api" "web" "nginx")
            if uses_qdrant_runtime; then
                api_services=("qdrant" "${api_services[@]}")
            fi
            if ! run_docker_compose "$docker_dir" "$compose_file" up -d "${api_services[@]}"; then
                log_error "Failed to restart ${api_services[*]}"
                return 1
            fi
            ;;
        "web")
            if ! run_docker_compose "$docker_dir" "$compose_file" up -d web nginx; then
                log_error "Failed to restart web, nginx"
                return 1
            fi
            ;;
        "nginx")
            if ! run_docker_compose "$docker_dir" "$compose_file" up -d nginx; then
                log_error "Failed to restart nginx"
                return 1
            fi
            ;;
        *)
            if ! run_docker_compose "$docker_dir" "$compose_file" up -d "$service"; then
                log_error "Failed to restart $service"
                return 1
            fi
            ;;
    esac
    return 0
}

# Function to ensure dependent services are running
ensure_dependent_services() {
    local docker_dir="${1:-$DOCKER_DIR}"
    local compose_file="${2:-docker-compose.yml}"
    local missing_services=()

    cd "$docker_dir" || return 1

    # Check if web and nginx are running
    if ! run_docker_compose "$docker_dir" "$compose_file" ps --format json web 2>/dev/null | grep -q '"State":"running"'; then
        missing_services+=("web")
    fi

    if ! run_docker_compose "$docker_dir" "$compose_file" ps --format json nginx 2>/dev/null | grep -q '"State":"running"'; then
        missing_services+=("nginx")
    fi

    if uses_qdrant_runtime && ! run_docker_compose "$docker_dir" "$compose_file" ps --format json qdrant 2>/dev/null | grep -q '"State":"running"'; then
        missing_services+=("qdrant")
    fi

    if [ "${#missing_services[@]}" -gt 0 ]; then
        log_info "Starting missing dependent services: ${missing_services[*]}"
        run_docker_compose "$docker_dir" "$compose_file" up -d "${missing_services[@]}"
    fi
}

# Function to start all services with health checking
start_services() {
    local docker_dir="${1:-$DOCKER_DIR}"
    local compose_file="${2:-docker-compose.yml}"

    cd "$docker_dir" || {
        log_error "Failed to change to Docker directory: $docker_dir"
        return 1
    }

    log_info "Starting containers using $compose_file..."
    if ! run_docker_compose "$docker_dir" "$compose_file" up -d; then
        log_error "Failed to start containers"
        return 1
    fi

    log_info "Waiting for services to become healthy..."

    if uses_qdrant_runtime; then
        wait_for_healthy "qdrant" 60 "$docker_dir" "$compose_file"
    fi

    # Wait for critical services to be healthy
    # Increased timeout to 180s for API (FastAPI + retrieval/index initialization needs 60-90s)
    local api_healthy=0
    if ! wait_for_healthy "api" 180 "$docker_dir" "$compose_file"; then
        api_healthy=1
    fi

    wait_for_healthy "bisq2-api" 300 "$docker_dir" "$compose_file"

    # Ensure dependent services are running
    ensure_dependent_services "$docker_dir" "$compose_file"

    # Final health check for web and nginx
    if [ $api_healthy -eq 0 ]; then
        wait_for_healthy "web" 60 "$docker_dir" "$compose_file"
        wait_for_healthy "nginx" 60 "$docker_dir" "$compose_file"
    fi

    # Check if any critical services failed
    if [ $api_healthy -ne 0 ]; then
        log_error "API service is not healthy. Check logs with:"
        log_error "docker compose -f $compose_file logs api"
        return 1
    fi

    return 0
}

# Function to stop all services
stop_services() {
    local docker_dir="${1:-$DOCKER_DIR}"
    local compose_file="${2:-docker-compose.yml}"

    cd "$docker_dir" || {
        log_error "Failed to change to Docker directory: $docker_dir"
        return 1
    }

    log_info "Stopping all services..."
    if ! run_docker_compose "$docker_dir" "$compose_file" down; then
        log_error "Failed to stop services"
        return 1
    fi

    log_success "All services stopped successfully"
    return 0
}

# Function to rebuild and restart services
service_has_build_configuration() {
    local service="$1"
    local docker_dir="${2:-$DOCKER_DIR}"
    local compose_file="${3:-docker-compose.yml}"
    local compose_config
    local build_state

    if ! command -v jq >/dev/null 2>&1; then
        log_error "jq is required to inspect the Compose build topology"
        return 2
    fi

    if ! compose_config=$(run_docker_compose "$docker_dir" "$compose_file" config --format json); then
        log_error "Failed to inspect the Compose build topology"
        return 2
    fi

    if ! build_state=$(printf '%s\n' "$compose_config" | jq -er \
        --arg service "$service" \
        'if .services[$service] == null then "missing" elif .services[$service].build == null then "absent" else "present" end'); then
        log_error "Compose returned an unreadable build topology"
        return 2
    fi

    case "$build_state" in
        present)
            return 0
            ;;
        absent)
            return 1
            ;;
        missing)
            log_error "Required Compose service is unavailable: $service"
            return 2
            ;;
        *)
            log_error "Compose returned an unknown build state"
            return 2
            ;;
    esac
}

rebuild_services() {
    local docker_dir="${1:-$DOCKER_DIR}"
    local compose_file="${2:-docker-compose.yml}"

    cd "$docker_dir" || {
        log_error "Failed to change to Docker directory: $docker_dir"
        return 1
    }

    local build_services=("api" "web" "bisq2-api")
    local rebuild_services=("api" "matrix-alert-relay" "web" "bisq2-api")
    local relay_build_status

    # Current deployments share the API image with the relay, while older
    # rollback targets define a separate relay build. Inspect the checked-out
    # Compose topology so either revision receives the image it declares.
    if service_has_build_configuration \
        "matrix-alert-relay" "$docker_dir" "$compose_file"; then
        build_services+=("matrix-alert-relay")
    else
        relay_build_status=$?
        if [ "$relay_build_status" -gt 1 ]; then
            return 1
        fi
    fi

    log_info "Stopping backend services (nginx stays running for maintenance page)..."
    if ! run_docker_compose "$docker_dir" "$compose_file" stop "${rebuild_services[@]}"; then
        log_error "Failed to stop backend services"
        return 1
    fi

    log_info "Building backend containers (pulling fresh base images)..."
    # Pass BUILD_ID as build arg for Next.js cache invalidation
    # BUILD_ID is set by update.sh via get_build_id() function
    if ! run_docker_compose "$docker_dir" "$compose_file" build --pull --build-arg BUILD_ID="${BUILD_ID:-bisq-support-build}" "${build_services[@]}"; then
        log_error "Failed to rebuild backend containers"
        return 1
    fi

    log_info "Starting rebuilt backend containers..."
    local runtime_services=("${rebuild_services[@]}")
    if uses_qdrant_runtime; then
        runtime_services=("qdrant" "${runtime_services[@]}")
    fi

    if ! run_docker_compose "$docker_dir" "$compose_file" up -d "${runtime_services[@]}"; then
        log_error "Failed to start backend containers"
        return 1
    fi

    log_info "Ensuring nginx and dependent services are running..."
    # Make sure nginx is up (in case it wasn't running)
    if ! run_docker_compose "$docker_dir" "$compose_file" up -d nginx; then
        log_warning "Failed to ensure nginx is running"
    fi

    log_info "Ensuring monitoring services are running..."
    # Start all monitoring services (if defined in compose file)
    # These services enhance observability; graceful degradation if unavailable
    local monitoring_services=("prometheus" "grafana" "node-exporter" "alertmanager" "cadvisor" "scheduler")
    local monitoring_failed=0
    for svc in "${monitoring_services[@]}"; do
        if run_docker_compose "$docker_dir" "$compose_file" up -d "$svc" 2>/dev/null; then
            log_success "Monitoring service $svc started"
        else
            log_warning "Monitoring service $svc may not be defined or failed to start"
            monitoring_failed=$((monitoring_failed + 1))
        fi
    done
    if [ $monitoring_failed -gt 0 ]; then
        log_warning "$monitoring_failed monitoring services failed to start"
    fi

    return 0
}

refresh_runtime_services() {
    local docker_dir="${1:-$DOCKER_DIR}"
    local compose_file="${2:-docker-compose.yml}"
    local services=("api" "matrix-alert-relay" "web" "nginx" "bisq2-api")

    if uses_qdrant_runtime; then
        services=("qdrant" "${services[@]}")
    fi

    cd "$docker_dir" || {
        log_error "Failed to change to Docker directory: $docker_dir"
        return 1
    }

    log_info "Refreshing runtime services to apply environment and compose changes..."
    run_docker_compose "$docker_dir" "$compose_file" up -d "${services[@]}"
}

reconcile_runtime_services() {
    local docker_dir="${1:-$DOCKER_DIR}"
    local compose_file="${2:-docker-compose.yml}"

    log_info "Reconciling runtime services..."
    if check_and_repair_services "$docker_dir" "$compose_file"; then
        return 0
    fi

    log_warning "Service repair was insufficient. Restarting the full runtime set..."
    if ! start_services "$docker_dir" "$compose_file"; then
        log_error "Failed to restart runtime services"
        return 1
    fi

    check_and_repair_services "$docker_dir" "$compose_file"
}

# Function to test the chat endpoint
test_chat_endpoint() {
    local url="${1:-http://localhost/api/chat/query}"
    local retries="${2:-5}"
    local delay="${3:-10}"
    local question="${CHAT_TEST_QUESTION:-In Bisq 2, how do I buy bitcoin with Bisq Easy?}"
    local required_answer_regex="${CHAT_TEST_REQUIRED_ANSWER_REGEX:-bisq}"
    local required_concept_regex="${CHAT_TEST_REQUIRED_CONCEPT_REGEX:-(bitcoin|btc)}"
    local required_domain_regex="${CHAT_TEST_REQUIRED_DOMAIN_REGEX:-(buy|purchase|seller|trade)}"
    local payload
    payload=$(jq -nc --arg question "$question" \
        '{question: $question, chat_history: [], bypass_hooks: ["escalation"]}')

    log_info "Testing chat endpoint..."

    local attempt=1
    while [ "$attempt" -le "$retries" ]; do
        local response
        local http_code

        # Get both response body and HTTP status code
        response=$(curl -s -w "\n%{http_code}" -X POST \
            -H "Content-Type: application/json" \
            -d "$payload" \
            "$url")

        # Extract HTTP code (last line) and body (everything else)
        http_code=$(echo "$response" | tail -n1)
        response=$(echo "$response" | sed '$d')

        # Validate HTTP code is numeric (curl may fail with connection errors)
        if ! [[ "$http_code" =~ ^[0-9]+$ ]]; then
            http_code="000"
        fi

        # Check if response contains expected fields and a substantive answer.
        if echo "$response" | jq -e '.answer and (.answer | type == "string") and (.answer | length > 20) and (.sources | type == "array") and (.sources | length > 0) and .response_time' > /dev/null 2>&1; then
            local answer_lower
            local signal_count=0
            answer_lower=$(echo "$response" | jq -r '.answer' | tr '[:upper:]' '[:lower:]')

            [[ "$answer_lower" =~ $required_answer_regex ]] && signal_count=$((signal_count + 1))
            [[ "$answer_lower" =~ $required_concept_regex ]] && signal_count=$((signal_count + 1))
            [[ "$answer_lower" =~ $required_domain_regex ]] && signal_count=$((signal_count + 1))

            if [ "$signal_count" -gt 0 ]; then
                if [ "$signal_count" -lt 3 ]; then
                    log_warning "Chat endpoint answer passed with partial content signals (${signal_count}/3)"
                fi
                log_success "Chat endpoint test successful"
                local response_time
                response_time=$(echo "$response" | jq -r '.response_time')
                log_success "Response time: ${response_time}"
                return 0
            else
                log_warning "Chat endpoint returned schema-valid but content-weak answer"
            fi
        fi

        # If we got a non-200 status or invalid response, retry
        if [ "$attempt" -lt "$retries" ]; then
            log_warning "Chat endpoint test failed (attempt $attempt/$retries, HTTP $http_code). Retrying in ${delay}s..."
            sleep "$delay"
        fi

        attempt=$((attempt + 1))
    done

    log_error "Chat endpoint test failed after $retries attempts. Last response: $response"
    return 1
}

is_mcp_live_data_enabled() {
    local env_file="${1:-${DOCKER_DIR:-}/.env}"
    local value="${ENABLE_BISQ_MCP_INTEGRATION:-}"

    if [ -z "$value" ] && [ -n "$env_file" ] && [ -f "$env_file" ]; then
        value=$(
            grep -E "^(export[[:space:]]+)?ENABLE_BISQ_MCP_INTEGRATION=" "$env_file" |
                tail -n1 |
                sed -E "s/^(export[[:space:]]+)?ENABLE_BISQ_MCP_INTEGRATION=//" ||
                true
        )
    fi

    value="${value%%#*}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value#\"}" ; value="${value%\"}"
    value="${value#\'}" ; value="${value%\'}"

    is_env_enabled "$value"
}

test_live_data_chat_endpoint() {
    local url="${1:-http://localhost/api/chat/query}"
    local retries="${2:-5}"
    local delay="${3:-10}"
    local env_file="${4:-${DOCKER_DIR:-}/.env}"
    local question="${LIVE_DATA_SMOKE_QUESTION:-What is the current BTC price?}"
    local payload

    if ! is_mcp_live_data_enabled "$env_file"; then
        log_warning \
            "Skipping MCP live-data smoke check because ENABLE_BISQ_MCP_INTEGRATION is disabled"
        return 0
    fi

    payload=$(jq -nc --arg question "$question" \
        '{question: $question, chat_history: [], bypass_hooks: ["escalation"]}')

    log_info "Testing MCP live-data chat endpoint..."

    local attempt=1
    while [ "$attempt" -le "$retries" ]; do
        local response
        local http_code

        response=$(curl -s -w "\n%{http_code}" -X POST \
            --connect-timeout 10 \
            --max-time 30 \
            -H "Content-Type: application/json" \
            -d "$payload" \
            "$url")

        http_code=$(echo "$response" | tail -n1)
        response=$(echo "$response" | sed '$d')

        if ! [[ "$http_code" =~ ^[0-9]+$ ]]; then
            http_code="000"
        fi

        if [[ "$http_code" =~ ^2[0-9][0-9]$ ]] && echo "$response" | jq -e '
            .answer
            and (.answer | type == "string")
            and (.mcp_tools_used | type == "array")
            and any(
                .mcp_tools_used[];
                .tool == "get_market_prices" or .tool == "get_offerbook"
            )
        ' > /dev/null 2>&1; then
            local tools
            tools=$(
                echo "$response" |
                    jq -r '[.mcp_tools_used[].tool] | unique | join(",")'
            )
            log_success "MCP live-data smoke test successful"
            log_success "MCP tools used: ${tools}"
            return 0
        fi

        if [ "$attempt" -lt "$retries" ]; then
            log_warning \
                "MCP live-data smoke test failed (attempt $attempt/$retries, HTTP $http_code). Retrying in ${delay}s..."
            sleep "$delay"
        fi

        attempt=$((attempt + 1))
    done

    log_error \
        "MCP live-data smoke test failed after $retries attempts. Last response: $response"
    return 1
}

# Function to display service status
show_service_status() {
    local docker_dir="${1:-$DOCKER_DIR}"
    local compose_file="${2:-docker-compose.yml}"

    cd "$docker_dir" || return 1

    echo ""
    log_info "Final Service Status:"
    run_docker_compose "$docker_dir" "$compose_file" ps
    echo ""
}

# Function to check all services and auto-restart failed ones
check_and_repair_services() {
    local docker_dir="${1:-$DOCKER_DIR}"
    local compose_file="${2:-docker-compose.yml}"
    local failed_services=()
    # All core and monitoring services are critical for production operation
    local critical_services=("api" "matrix-alert-relay" "web" "nginx" "prometheus" "grafana" "node-exporter" "scheduler" "alertmanager")
    local all_services=("nginx" "web" "api" "matrix-alert-relay" "bisq2-api" "prometheus" "grafana" "node-exporter" "scheduler" "alertmanager" "cadvisor")

    if uses_qdrant_runtime; then
        critical_services=("qdrant" "${critical_services[@]}")
        all_services=("qdrant" "${all_services[@]}")
    fi

    cd "$docker_dir" || return 1

    # The currently loaded helpers can outlive a rollback's git reset. Keep the
    # relay critical when the checked-out Compose file defines it, but do not
    # try to repair a service that does not exist in an older revision.
    local compose_services
    local relay_service_defined=1
    if compose_services=$(run_docker_compose "$docker_dir" "$compose_file" config --services 2>/dev/null); then
        relay_service_defined=0
        local defined_service
        while IFS= read -r defined_service; do
            if [ "$defined_service" = "matrix-alert-relay" ]; then
                relay_service_defined=1
                break
            fi
        done <<< "$compose_services"
    fi

    log_info "Checking all services..."
    echo ""

    # Check all services and separate critical from non-critical failures
    local failed_critical=()
    for service in "${all_services[@]}"; do
        if [ "$service" = "matrix-alert-relay" ] && [ "$relay_service_defined" -eq 0 ]; then
            continue
        fi
        if ! check_service "$service" "$docker_dir" "$compose_file"; then
            failed_services+=("$service")
            # Check if this is a critical service
            case " ${critical_services[*]} " in
              *" ${service} "*)
                failed_critical+=("$service")
                ;;
            esac
        fi
    done

    # If no services failed, exit successfully
    if [ ${#failed_services[@]} -eq 0 ]; then
        echo ""
        log_success "All services are healthy!"
        return 0
    fi

    echo ""
    log_warning "Found ${#failed_services[@]} unhealthy service(s): ${failed_services[*]}"

    # If only non-critical services failed, consider it a success
    # (non-critical services like bisq2-api may still be starting)
    if [ ${#failed_critical[@]} -eq 0 ]; then
        echo ""
        log_warning "Only non-critical services are unhealthy. Continuing..."
        return 0
    fi

    # Auto-restart failed critical services
    local restarted_services=()
    local restart_failed=0
    for service in "${failed_critical[@]}"; do
        echo ""
        log_info "Auto-restarting critical service: $service"
        if restart_service_with_deps "$service" "$docker_dir" "$compose_file"; then
            restarted_services+=("$service")
        else
            restart_failed=1
            log_error "Failed to restart $service - skipping health check"
            # Continue to try other services instead of failing immediately
        fi
    done

    # Wait for restarted services to become healthy
    if [ ${#restarted_services[@]} -gt 0 ]; then
        echo ""
        log_info "Waiting for restarted services to become healthy..."
        local restart_wait_time="${RESTART_WAIT_TIME:-10}"
        sleep "$restart_wait_time"  # Initial wait for services to start

        local any_unhealthy=0
        for service in "${restarted_services[@]}"; do
            if ! wait_for_healthy "$service" 120 "$docker_dir" "$compose_file"; then
                any_unhealthy=1
            fi
        done

        if [ $restart_failed -eq 0 ] && [ $any_unhealthy -eq 0 ]; then
            echo ""
            log_success "All restarted services are now healthy!"
            return 0
        else
            echo ""
            log_error "Some services failed to become healthy after restart"
            return 1
        fi
    elif [ $restart_failed -eq 1 ]; then
        echo ""
        log_error "Some critical services failed to restart"
        return 1
    else
        echo ""
        log_error "Critical services failed but restart was unsuccessful"
        return 1
    fi
}

# Export all functions
export -f check_service
export -f wait_for_healthy
export -f check_completed_service
export -f wait_for_compose_health
export -f check_container_health
export -f restart_service_with_deps
export -f ensure_dependent_services
export -f start_services
export -f stop_services
export -f rebuild_services
export -f refresh_runtime_services
export -f reconcile_runtime_services
export -f test_chat_endpoint
export -f is_mcp_live_data_enabled
export -f test_live_data_chat_endpoint
export -f show_service_status
export -f check_and_repair_services

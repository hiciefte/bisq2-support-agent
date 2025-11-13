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
    status=$(docker compose -f "$docker_dir/$compose_file" ps --format json "$service" 2>/dev/null)

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

    while [ $waited -lt $max_wait ]; do
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
            if ! docker compose -f "$compose_file" up -d api web nginx; then
                log_error "Failed to restart api, web, nginx"
                return 1
            fi
            ;;
        "web")
            if ! docker compose -f "$compose_file" up -d web nginx; then
                log_error "Failed to restart web, nginx"
                return 1
            fi
            ;;
        "nginx")
            if ! docker compose -f "$compose_file" up -d nginx; then
                log_error "Failed to restart nginx"
                return 1
            fi
            ;;
        *)
            if ! docker compose -f "$compose_file" up -d "$service"; then
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
    local missing_services=""

    cd "$docker_dir" || return 1

    # Check if web and nginx are running
    if ! docker compose -f "$compose_file" ps --format json web 2>/dev/null | grep -q '"State":"running"'; then
        missing_services="$missing_services web"
    fi

    if ! docker compose -f "$compose_file" ps --format json nginx 2>/dev/null | grep -q '"State":"running"'; then
        missing_services="$missing_services nginx"
    fi

    if [ -n "$missing_services" ]; then
        log_info "Starting missing dependent services:$missing_services"
        docker compose -f "$compose_file" up -d $missing_services
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
    if ! docker compose -f "$compose_file" up -d; then
        log_error "Failed to start containers"
        return 1
    fi

    log_info "Waiting for services to become healthy..."

    # Wait for critical services to be healthy
    # Increased timeout to 180s for API (FastAPI + ChromaDB initialization needs 60-90s)
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
    if ! docker compose -f "$compose_file" down; then
        log_error "Failed to stop services"
        return 1
    fi

    log_success "All services stopped successfully"
    return 0
}

# Function to rebuild and restart services
rebuild_services() {
    local docker_dir="${1:-$DOCKER_DIR}"
    local compose_file="${2:-docker-compose.yml}"

    cd "$docker_dir" || {
        log_error "Failed to change to Docker directory: $docker_dir"
        return 1
    }

    # Define services that need rebuilding (excludes nginx and monitoring)
    local rebuild_services=("api" "web" "bisq2-api")

    log_info "Stopping backend services (nginx stays running for maintenance page)..."
    if ! docker compose -f "$compose_file" stop "${rebuild_services[@]}"; then
        log_error "Failed to stop backend services"
        return 1
    fi

    log_info "Building backend containers (pulling fresh base images)..."
    if ! docker compose -f "$compose_file" build --pull "${rebuild_services[@]}"; then
        log_error "Failed to rebuild backend containers"
        return 1
    fi

    log_info "Starting rebuilt backend containers..."
    if ! docker compose -f "$compose_file" up -d "${rebuild_services[@]}"; then
        log_error "Failed to start backend containers"
        return 1
    fi

    log_info "Ensuring nginx and dependent services are running..."
    # Make sure nginx is up (in case it wasn't running)
    if ! docker compose -f "$compose_file" up -d nginx; then
        log_warning "Failed to ensure nginx is running"
    fi

    return 0
}

# Function to test the chat endpoint
test_chat_endpoint() {
    local url="${1:-http://localhost/api/chat/query}"

    log_info "Testing chat endpoint..."
    local response
    response=$(curl -s -X POST \
        -H "Content-Type: application/json" \
        -d '{
            "question": "What is Bisq?",
            "chat_history": []
        }' \
        "$url")

    # Check if response contains expected fields
    if echo "$response" | jq -e '.answer and .sources and .response_time' > /dev/null; then
        log_success "Chat endpoint test successful"
        local response_time
        response_time=$(echo "$response" | jq -r '.response_time')
        log_success "Response time: ${response_time}"
        return 0
    else
        log_error "Chat endpoint test failed. Response: $response"
        return 1
    fi
}

# Function to display service status
show_service_status() {
    local docker_dir="${1:-$DOCKER_DIR}"
    local compose_file="${2:-docker-compose.yml}"

    cd "$docker_dir" || return 1

    echo ""
    log_info "Final Service Status:"
    docker compose -f "$compose_file" ps
    echo ""
}

# Function to check all services and auto-restart failed ones
check_and_repair_services() {
    local docker_dir="${1:-$DOCKER_DIR}"
    local compose_file="${2:-docker-compose.yml}"
    local failed_services=()
    local critical_services=("api" "web" "nginx")
    local all_services=("nginx" "web" "api" "bisq2-api" "prometheus" "grafana" "node-exporter" "scheduler")

    cd "$docker_dir" || return 1

    log_info "Checking all services..."
    echo ""

    # Check all services and separate critical from non-critical failures
    local failed_critical=()
    for service in "${all_services[@]}"; do
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
export -f check_container_health
export -f restart_service_with_deps
export -f ensure_dependent_services
export -f start_services
export -f stop_services
export -f rebuild_services
export -f test_chat_endpoint
export -f show_service_status
export -f check_and_repair_services

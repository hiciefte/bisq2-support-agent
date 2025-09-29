#!/bin/bash
set -e

# Health Check Monitoring Script for Bisq Support Assistant
# This script monitors the health of all services and automatically restarts failed dependencies

# --- Get Project Root ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
DOCKER_DIR="$PROJECT_ROOT/docker"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "========================================================"
echo "🔍 Bisq Support Assistant - Health Check Monitor"
echo "========================================================"

# Navigate to the Docker directory
cd "$DOCKER_DIR" || {
    echo -e "${RED}Error: Failed to change to Docker directory: $DOCKER_DIR${NC}"
    exit 1
}

# Function to check service health
check_service() {
    local service=$1
    local status=$(docker compose -f docker-compose.yml ps --format json "$service" 2>/dev/null)

    if [ -z "$status" ]; then
        echo -e "${RED}❌ $service: NOT FOUND${NC}"
        return 2
    fi

    local state=$(echo "$status" | jq -r '.State' 2>/dev/null || echo "unknown")
    local health=$(echo "$status" | jq -r '.Health' 2>/dev/null || echo "none")

    case "$state" in
        "running")
            if [ "$health" = "healthy" ]; then
                echo -e "${GREEN}✅ $service: HEALTHY${NC}"
                return 0
            elif [ "$health" = "unhealthy" ]; then
                echo -e "${RED}🔴 $service: UNHEALTHY${NC}"
                return 1
            elif [ "$health" = "starting" ]; then
                echo -e "${YELLOW}⏳ $service: STARTING${NC}"
                return 1
            else
                echo -e "${GREEN}✅ $service: RUNNING (no health check)${NC}"
                return 0
            fi
            ;;
        "exited")
            echo -e "${RED}❌ $service: EXITED${NC}"
            return 1
            ;;
        "restarting")
            echo -e "${YELLOW}🔄 $service: RESTARTING${NC}"
            return 1
            ;;
        *)
            echo -e "${YELLOW}⚠️ $service: $state${NC}"
            return 1
            ;;
    esac
}

# Function to restart a service and its dependencies
restart_service_with_deps() {
    local service=$1
    echo -e "${BLUE}🔄 Restarting $service and dependent services...${NC}"

    case "$service" in
        "api")
            docker compose -f docker-compose.yml up -d api web nginx
            ;;
        "web")
            docker compose -f docker-compose.yml up -d web nginx
            ;;
        "nginx")
            docker compose -f docker-compose.yml up -d nginx
            ;;
        *)
            docker compose -f docker-compose.yml up -d "$service"
            ;;
    esac
}

# Function to wait for service to become healthy
wait_for_healthy() {
    local service=$1
    local max_wait=${2:-60}  # Default 60 seconds
    local waited=0

    echo -e "${BLUE}⏳ Waiting for $service to become healthy...${NC}"

    while [ $waited -lt $max_wait ]; do
        if check_service "$service" >/dev/null 2>&1; then
            echo -e "${GREEN}✅ $service is now healthy${NC}"
            return 0
        fi
        sleep 5
        waited=$((waited + 5))
    done

    echo -e "${RED}❌ $service did not become healthy within ${max_wait}s${NC}"
    return 1
}

# Main health check logic
main() {
    local failed_services=()
    local critical_services=("api" "web" "nginx")
    local all_services=("nginx" "web" "api" "bisq2-api" "prometheus" "grafana" "node-exporter" "scheduler")

    echo -e "${BLUE}Checking all services...${NC}"
    echo ""

    # Check all services
    for service in "${all_services[@]}"; do
        if ! check_service "$service"; then
            failed_services+=("$service")
        fi
    done

    # If no services failed, exit successfully
    if [ ${#failed_services[@]} -eq 0 ]; then
        echo ""
        echo -e "${GREEN}🎉 All services are healthy!${NC}"
        exit 0
    fi

    echo ""
    echo -e "${YELLOW}⚠️ Found ${#failed_services[@]} unhealthy service(s): ${failed_services[*]}${NC}"

    # Auto-restart failed critical services
    local restarted_services=()
    for service in "${failed_services[@]}"; do
        if [[ " ${critical_services[*]} " =~ " ${service} " ]]; then
            echo ""
            echo -e "${BLUE}🔧 Auto-restarting critical service: $service${NC}"
            restart_service_with_deps "$service"
            restarted_services+=("$service")
        fi
    done

    # Wait for restarted services to become healthy
    if [ ${#restarted_services[@]} -gt 0 ]; then
        echo ""
        echo -e "${BLUE}⏳ Waiting for restarted services to become healthy...${NC}"
        sleep 10  # Initial wait for services to start

        local all_healthy=true
        for service in "${restarted_services[@]}"; do
            if [[ " ${critical_services[*]} " =~ " ${service} " ]]; then
                if ! wait_for_healthy "$service" 120; then  # 2 minutes wait
                    all_healthy=false
                fi
            fi
        done

        if [ "$all_healthy" = true ]; then
            echo ""
            echo -e "${GREEN}✅ All restarted services are now healthy!${NC}"
            exit 0
        else
            echo ""
            echo -e "${RED}❌ Some services failed to become healthy after restart${NC}"
            exit 1
        fi
    else
        echo ""
        echo -e "${YELLOW}ℹ️ No critical services needed restart. Manual intervention may be required.${NC}"
        exit 1
    fi
}

# Handle script arguments
case "${1:-}" in
    "--help"|"-h")
        echo "Usage: $0 [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  --help, -h    Show this help message"
        echo "  --quiet, -q   Suppress non-essential output"
        echo "  --json        Output status in JSON format"
        echo ""
        echo "This script checks the health of all Bisq Support Assistant services"
        echo "and automatically restarts failed critical services."
        exit 0
        ;;
    "--quiet"|"-q")
        # Run main function but suppress some output
        main 2>/dev/null
        ;;
    "--json")
        # JSON output for monitoring systems
        docker compose -f docker-compose.yml ps --format json | jq -s '.'
        ;;
    "")
        # Default behavior
        main
        ;;
    *)
        echo -e "${RED}Unknown option: $1${NC}"
        echo "Use --help for usage information."
        exit 1
        ;;
esac
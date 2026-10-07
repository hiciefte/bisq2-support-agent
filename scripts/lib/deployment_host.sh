#!/usr/bin/env bash
# Fixed adapters for the checked-in host backend; never source update.sh main.
set -Eeuo pipefail
LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=scripts/lib/common.sh
source "$LIB_DIR/common.sh"
# shellcheck source=scripts/lib/docker-utils.sh
source "$LIB_DIR/docker-utils.sh"
# shellcheck source=scripts/lib/git-utils.sh
source "$LIB_DIR/git-utils.sh"
setup_colors

action=${1:?}; shift
if [ "$action" = lock ] || [ "$action" = inspect ]; then
    install=${1:?}; python=${2:?}; shift 2
    # The only executable payload is our checked-in stdio owner.
    mode=--read-only
    if [ "$action" = lock ]; then
        acquire_production_lifecycle_lock "$install" >&2
        mode=--locked
    fi
    exec "$python" -I -B "$LIB_DIR/../deploy_release_host.py" "$mode" "$@"
fi

install=${1:?}; project=${2:?}; shift 2
DOCKER_DIR="$install/docker"
INSTALL_DIR="$install"
COMPOSE_FILE=docker-compose.yml
# Use the library's default deploy.env path, not the remaining action arguments.
# shellcheck disable=SC2119
source_deploy_paths >&2 || true
test "${BISQ_SUPPORT_INSTALL_DIR:-$install}" = "$install"
export COMPOSE_PROJECT_NAME="$project"
pin_existing_compose_project \
    "$DOCKER_DIR" "$COMPOSE_FILE" existing deployment-owner >&2

case "$action" in
    config)
        test "$#" -eq 0
        run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" config --format json
        ;;
    build-id)
        test "$#" -eq 1
        get_build_id "$1"
        ;;
    quality)
        test "$#" -eq 3
        "$LIB_DIR/../verify-release-ai-quality-gate.sh" \
            --repository "$1" --commit "$2" --remote "$3" \
            --env-file "$DOCKER_DIR/.env"
        ;;
    build)
        test "$#" -eq 3
        overlay=$1; service=$2; build_id=$3
        case "$service" in api|web) ;; *) exit 2;; esac
        run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" -f "$overlay" \
            build --build-arg "BUILD_ID=$build_id" "$service"
        ;;
    switch)
        test "$#" -eq 2
        overlay=$1; service=$2
        case "$service" in api|web) ;; *) exit 2;; esac
        run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" -f "$overlay" \
            up -d --no-deps --no-build --pull never "$service"
        ;;
    health)
        test "$#" -eq 2
        case "$1" in api|web) ;; *) exit 2;; esac
        wait_for_healthy "$1" "$2" "$DOCKER_DIR" "$COMPOSE_FILE"
        ;;
    smoke)
        test "$#" -eq 2
        case "$1" in
            standard) test_chat_endpoint "$2/api/chat/query";;
            live_mcp)
                # A skipped optional smoke is not successful release evidence.
                is_mcp_live_data_enabled "$DOCKER_DIR/.env"
                test_live_data_chat_endpoint "$2/api/chat/query" 1 0 "$DOCKER_DIR/.env"
                ;;
            *) exit 2;;
        esac
        ;;
    *) exit 2;;
esac

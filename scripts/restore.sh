#!/bin/bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." &>/dev/null && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"
setup_colors

BACKUP_FILE=""
ENCRYPTION="auto"
AGE_IDENTITY_FILE="${BACKUP_AGE_IDENTITY_FILE:-}"
VERIFY_ONLY=false
APPLY=false
CONFIRMED=false
QDRANT_COLLECTION=""
INSTALL_DIR=""
DOCKER_DIR=""
DATA_DIR=""
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
DR_HELPER=""
WORK_DIR=""
LOCK_FD=""
SCRATCH_QDRANT_CONTAINER=""
SCRATCH_QDRANT_NETWORK=""
SCRATCH_QDRANT_VOLUME=""
APPLICATION_RESTORE_STARTED=false
QDRANT_ROLLBACK_AVAILABLE=false
RESTORE_COMMITTED=false
declare -a COMPONENTS=()
declare -a STOPPED_SERVICES=()
declare -a RESTORED_VOLUME_COMPONENTS=()
declare -a RESTORED_VOLUME_NAMES=()
declare -a RESTORED_VOLUME_IMAGES=()

initialize_paths() {
    source_deploy_paths >&2 || true
    INSTALL_DIR="${BISQ_SUPPORT_INSTALL_DIR:-$PROJECT_ROOT}"
    INSTALL_DIR="$(cd "$INSTALL_DIR" && pwd -P)"
    DOCKER_DIR="$INSTALL_DIR/docker"
    DATA_DIR="$INSTALL_DIR/api/data"
    DR_HELPER="$INSTALL_DIR/api/app/scripts/disaster_recovery.py"
}

usage() {
    cat <<'EOF'
Usage:
  restore.sh --backup FILE --verify [--component NAME ...]
  restore.sh --backup FILE --apply --yes [--component NAME ...]

Modes:
  --verify                 Decrypt, restore into scratch, and run sanity checks
  --apply --yes            Restore selected live components after verification

Selection (repeatable; default: all):
  --component NAME         application, sqlite, matrix, qdrant, prometheus,
                           grafana, bisq2, alertmanager, or all
  --qdrant-collection NAME Restore one Qdrant collection from the selected set

Decryption:
  --encryption auto|age|gpg
  --identity FILE          age identity file (or BACKUP_AGE_IDENTITY_FILE)

The backup intentionally contains only the names from docker/.env. It never
restores configuration values or encryption keys.
EOF
}

parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --backup)
                [ "$#" -ge 2 ] || { log_error "--backup requires a value"; return 2; }
                BACKUP_FILE="$2"
                shift 2
                ;;
            --verify)
                VERIFY_ONLY=true
                shift
                ;;
            --apply)
                APPLY=true
                shift
                ;;
            --yes)
                CONFIRMED=true
                shift
                ;;
            --component)
                [ "$#" -ge 2 ] || { log_error "--component requires a value"; return 2; }
                COMPONENTS+=("$2")
                shift 2
                ;;
            --qdrant-collection)
                [ "$#" -ge 2 ] || { log_error "--qdrant-collection requires a value"; return 2; }
                QDRANT_COLLECTION="$2"
                shift 2
                ;;
            --encryption)
                [ "$#" -ge 2 ] || { log_error "--encryption requires a value"; return 2; }
                ENCRYPTION="$2"
                shift 2
                ;;
            --identity)
                [ "$#" -ge 2 ] || { log_error "--identity requires a value"; return 2; }
                AGE_IDENTITY_FILE="$2"
                shift 2
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                usage
                return 2
                ;;
        esac
    done
}

compose() {
    run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" "$@"
}

component_selected() {
    local wanted="$1"
    local component
    for component in "${COMPONENTS[@]}"; do
        if [ "$component" = all ] || [ "$component" = "$wanted" ]; then
            return 0
        fi
    done
    return 1
}

validate_selection() {
    local component
    if [ "${#COMPONENTS[@]}" -eq 0 ]; then
        COMPONENTS=(all)
    fi
    for component in "${COMPONENTS[@]}"; do
        case "$component" in
            all|application|sqlite|matrix|qdrant|prometheus|grafana|bisq2|alertmanager) ;;
            *)
                log_error "Unknown restore component: $component"
                return 2
                ;;
        esac
    done
    if [ -n "$QDRANT_COLLECTION" ] && ! component_selected qdrant; then
        log_error "--qdrant-collection requires the qdrant component"
        return 2
    fi
}

detect_encryption() {
    if [ "$ENCRYPTION" = auto ]; then
        case "$BACKUP_FILE" in
            *.age) ENCRYPTION=age ;;
            *.gpg) ENCRYPTION=gpg ;;
            *)
                log_error "Could not detect backup encryption format"
                return 2
                ;;
        esac
    fi
    case "$ENCRYPTION" in
        age)
            [ -n "$AGE_IDENTITY_FILE" ] || {
                log_error "An age identity file is required"
                return 2
            }
            if [ ! -f "$AGE_IDENTITY_FILE" ] || [ -L "$AGE_IDENTITY_FILE" ]; then
                log_error "Age identity file is unavailable or unsafe"
                return 2
            fi
            check_required_commands age || return 1
            ;;
        gpg)
            check_required_commands gpg || return 1
            ;;
        *)
            log_error "Encryption must be auto, age, or gpg"
            return 2
            ;;
    esac
}

validate_configuration() {
    [ -n "$BACKUP_FILE" ] || { log_error "--backup is required"; return 2; }
    if [ ! -f "$BACKUP_FILE" ] || [ -L "$BACKUP_FILE" ]; then
        log_error "Backup file is unavailable or unsafe"
        return 2
    fi
    if [ "$VERIFY_ONLY" = "$APPLY" ]; then
        log_error "Choose exactly one of --verify or --apply"
        return 2
    fi
    if [ "$APPLY" = true ] && [ "$CONFIRMED" != true ]; then
        log_error "Live restore requires --yes"
        return 2
    fi
    validate_selection
    detect_encryption
    check_required_commands python3 mktemp rm flock || return 1
    [ -f "$DR_HELPER" ] || { log_error "Disaster-recovery helper is missing"; return 1; }

    if [ "$APPLY" = true ] || component_selected qdrant; then
        check_required_commands docker tar grep || return 1
        check_docker_daemon || return 1
        check_docker_compose || return 1
    fi
    if [ "$APPLY" = true ]; then
        [ -d "$DATA_DIR" ] || { log_error "Application data directory is missing"; return 1; }
    fi
}

start_stopped_services() {
    if [ "${#STOPPED_SERVICES[@]}" -eq 0 ]; then
        return 0
    fi
    log_info "Restarting services stopped for restore"
    if ! compose start "${STOPPED_SERVICES[@]}" >/dev/null; then
        log_error "Could not restart every service stopped for restore"
        return 1
    fi
    STOPPED_SERVICES=()
}

cleanup() {
    local exit_code=$?
    local preserve_work_dir=false
    set +e
    if ! cleanup_scratch_qdrant && [ "$exit_code" -eq 0 ]; then
        exit_code=1
    fi
    if [ "$exit_code" -ne 0 ] \
        && [ "$APPLY" = true ] \
        && [ "$RESTORE_COMMITTED" != true ]; then
        log_warning "Restore failed; rolling back every component already changed"
        if rollback_applied_components; then
            log_warning "Restore rollback completed"
        else
            preserve_work_dir=true
            log_error "Automatic rollback was incomplete"
        fi
    fi
    if [ "$preserve_work_dir" = false ]; then
        if ! start_stopped_services && [ "$exit_code" -eq 0 ]; then
            exit_code=1
        fi
    elif [ "${#STOPPED_SERVICES[@]}" -gt 0 ]; then
        log_error "Services remain stopped until a human completes rollback"
    fi
    if [ "$preserve_work_dir" = false ] \
        && [ -n "$WORK_DIR" ] \
        && [ -d "$WORK_DIR" ]; then
        rm -rf -- "$WORK_DIR"
    elif [ "$preserve_work_dir" = true ]; then
        log_error "Private rollback material preserved at: $WORK_DIR"
    fi
    if [ -n "$LOCK_FD" ]; then
        flock -u "$LOCK_FD"
    fi
    exit "$exit_code"
}

decrypt_backup() {
    local snapshot_root="$1"
    log_info "Decrypting backup into scratch storage"
    if [ "$ENCRYPTION" = age ]; then
        age --decrypt --identity "$AGE_IDENTITY_FILE" "$BACKUP_FILE" | \
            python3 "$DR_HELPER" extract-stream --destination "$snapshot_root" >/dev/null
    else
        gpg --batch --quiet --decrypt "$BACKUP_FILE" | \
            python3 "$DR_HELPER" extract-stream --destination "$snapshot_root" >/dev/null
    fi
}

verify_snapshot() {
    local snapshot_root="$1"
    local scratch_root="$2"
    local -a args=()
    local component
    for component in "${COMPONENTS[@]}"; do
        args+=(--component "$component")
    done
    log_info "Restoring selected components into scratch and verifying them"
    python3 "$DR_HELPER" verify-bundle \
        --snapshot-root "$snapshot_root" \
        --scratch-root "$scratch_root" \
        "${args[@]}"
}

container_id_for_service() {
    local container_id
    container_id="$(compose ps --all -q "$1")"
    if [ -z "$container_id" ]; then
        log_error "Required service container is unavailable: $1" >&2
        return 1
    fi
    printf '%s\n' "$container_id"
}

container_env_value() {
    local service="$1"
    local variable="$2"
    local container_id
    local entry
    local format
    [[ "$variable" =~ ^[A-Z_][A-Z0-9_]*$ ]] || return 2
    container_id="$(container_id_for_service "$service")" || return 1
    format="{{range .Config.Env}}{{if eq (index (split . \"=\") 0) \"$variable\"}}{{println .}}{{end}}{{end}}"
    entry="$(docker inspect --format "$format" "$container_id")" || return 1
    printf '%s\n' "${entry#*=}"
}

validate_api_data_mount() {
    local container_id
    local effective_data_dir
    local mount_type
    local mount_source
    local expected_source
    local canonical_source
    local entry
    local format

    container_id="$(container_id_for_service api)" || return 1
    format='{{range .Config.Env}}{{if eq (index (split . "=") 0) "DATA_DIR"}}{{println .}}{{end}}{{end}}'
    entry="$(docker inspect --format "$format" "$container_id")" || {
        log_error "Could not inspect the API container data directory"
        return 1
    }
    effective_data_dir="${entry#*=}"
    if [ "$effective_data_dir" != /data ]; then
        log_error "API container DATA_DIR must be /data for disaster recovery"
        return 1
    fi

    mount_type="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{println .Type}}{{end}}{{end}}' "$container_id")" || {
        log_error "Could not inspect the API container data mount"
        return 1
    }
    if [ "$mount_type" != bind ]; then
        log_error "API container /data must be a bind mount"
        return 1
    fi
    mount_source="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{println .Source}}{{end}}{{end}}' "$container_id")" || {
        log_error "Could not inspect the API container data mount source"
        return 1
    }
    if [ ! -d "$mount_source" ]; then
        log_error "API container /data bind source is unavailable"
        return 1
    fi
    expected_source="$(cd "$INSTALL_DIR/api/data" && pwd -P)" || {
        log_error "Expected application data directory is unavailable"
        return 1
    }
    canonical_source="$(cd "$mount_source" && pwd -P)" || {
        log_error "Could not resolve the API container data mount source"
        return 1
    }
    if [ "$canonical_source" != "$expected_source" ]; then
        log_error "API container /data bind source does not match the installation data directory"
        return 1
    fi
}

volume_for_service_path() {
    local service="$1"
    local destination="$2"
    local container_id
    local volume_name=""
    local name
    local mount_path

    container_id="$(container_id_for_service "$service")" || return 1
    while read -r name mount_path; do
        if [ "$mount_path" = "$destination" ]; then
            volume_name="$name"
            break
        fi
    done < <(docker inspect --format '{{range .Mounts}}{{println .Name .Destination}}{{end}}' "$container_id")
    if [ -z "$volume_name" ] || [ "$volume_name" = "<no" ]; then
        log_error "Required named volume is unavailable for $service" >&2
        return 1
    fi
    printf '%s\n' "$volume_name"
}

image_id_for_service() {
    local container_id
    container_id="$(container_id_for_service "$1")" || return 1
    docker inspect --format '{{.Image}}' "$container_id"
}

cleanup_scratch_qdrant() {
    local status=0
    if [ -n "$SCRATCH_QDRANT_CONTAINER" ]; then
        if docker rm -f "$SCRATCH_QDRANT_CONTAINER" >/dev/null 2>&1; then
            SCRATCH_QDRANT_CONTAINER=""
        else
            status=1
        fi
    fi
    if [ -n "$SCRATCH_QDRANT_VOLUME" ]; then
        if docker volume rm "$SCRATCH_QDRANT_VOLUME" >/dev/null 2>&1; then
            SCRATCH_QDRANT_VOLUME=""
        else
            status=1
        fi
    fi
    if [ -n "$SCRATCH_QDRANT_NETWORK" ]; then
        if docker network rm "$SCRATCH_QDRANT_NETWORK" >/dev/null 2>&1; then
            SCRATCH_QDRANT_NETWORK=""
        else
            status=1
        fi
    fi
    return "$status"
}

run_scratch_qdrant_helper() {
    local api_image="$1"
    shift
    docker run --rm -i \
        --network "$SCRATCH_QDRANT_NETWORK" \
        --read-only \
        --tmpfs /tmp:rw,nosuid,nodev,size=256m \
        --cap-drop ALL \
        --security-opt no-new-privileges \
        --user "${APP_UID:-1001}:${APP_GID:-1001}" \
        --env PYTHONDONTWRITEBYTECODE=1 \
        --env QDRANT_HOST=qdrant-scratch \
        --env QDRANT_PORT=6333 \
        --env QDRANT_API_KEY= \
        --volume "$DR_HELPER:/app/app/scripts/disaster_recovery.py:ro" \
        --entrypoint python \
        "$api_image" -m app.scripts.disaster_recovery "$@"
}

verify_qdrant_in_scratch() {
    local snapshot_root="$1"
    local api_image
    local qdrant_image
    local suffix
    component_selected qdrant || return 0

    api_image="$(image_id_for_service api)"
    qdrant_image="$(image_id_for_service qdrant)"
    suffix="$$-$RANDOM"
    SCRATCH_QDRANT_CONTAINER="bisq-support-qdrant-verify-$suffix"
    SCRATCH_QDRANT_NETWORK="bisq-support-qdrant-verify-$suffix"
    SCRATCH_QDRANT_VOLUME="bisq-support-qdrant-verify-$suffix"

    log_info "Restoring Qdrant snapshots into an isolated scratch service"
    docker network create --internal "$SCRATCH_QDRANT_NETWORK" >/dev/null
    docker volume create "$SCRATCH_QDRANT_VOLUME" >/dev/null
    docker run --detach \
        --name "$SCRATCH_QDRANT_CONTAINER" \
        --network "$SCRATCH_QDRANT_NETWORK" \
        --network-alias qdrant-scratch \
        --cap-drop ALL \
        --security-opt no-new-privileges \
        --volume "$SCRATCH_QDRANT_VOLUME:/qdrant/storage" \
        "$qdrant_image" >/dev/null

    run_scratch_qdrant_helper "$api_image" qdrant-wait --timeout 60 </dev/null
    run_scratch_qdrant_helper "$api_image" qdrant-import \
        < "$snapshot_root/components/qdrant/qdrant-snapshots.tar.gz"
    cleanup_scratch_qdrant
}

service_is_running() {
    local running_services
    running_services="$(compose ps --status running --services)" || return 2
    grep -Fxq "$1" <<< "$running_services"
}

stop_service_once() {
    local service="$1"
    local recorded
    local status
    if [ "${#STOPPED_SERVICES[@]}" -gt 0 ]; then
        for recorded in "${STOPPED_SERVICES[@]}"; do
            [ "$recorded" = "$service" ] && return 0
        done
    fi
    if service_is_running "$service"; then
        log_info "Stopping $service for restore"
        STOPPED_SERVICES+=("$service")
        compose stop --timeout 30 "$service" >/dev/null
    else
        status=$?
        if [ "$status" -ne 1 ]; then
            log_error "Could not determine whether $service is running"
            return "$status"
        fi
    fi
}

stop_selected_services() {
    if component_selected application \
        || component_selected sqlite \
        || component_selected matrix \
        || component_selected qdrant; then
        stop_service_once api
        stop_service_once scheduler
    fi
    if component_selected alertmanager; then
        stop_service_once alertmanager
    fi
    if component_selected matrix; then
        stop_service_once matrix-alert-relay
    fi
    if component_selected prometheus; then
        stop_service_once prometheus
    fi
    if component_selected grafana; then
        stop_service_once grafana
    fi
    if component_selected bisq2; then
        stop_service_once bisq2-api
    fi
}

snapshot_live_volume() {
    local volume_name="$1"
    local helper_image="$2"
    local output_archive="$3"
    docker run --rm \
        --network none --read-only --user 0:0 --cap-drop ALL \
        --cap-add DAC_READ_SEARCH \
        --security-opt no-new-privileges \
        --volume "$volume_name:/source:ro" \
        --entrypoint tar "$helper_image" \
        -C /source -czf - . > "$output_archive"
    tar -tzf "$output_archive" >/dev/null
}

extract_live_volume() {
    local volume_name="$1"
    local helper_image="$2"
    local source_archive="$3"
    docker run --rm -i \
        --network none --read-only --user 0:0 --cap-drop ALL \
        --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
        --security-opt no-new-privileges \
        --volume "$volume_name:/target" \
        --entrypoint sh "$helper_image" -c \
        'find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} \; && tar -C /target -xzf -' \
        < "$source_archive"
}

restore_volume_archive() {
    local component="$1"
    local volume_name="$2"
    local helper_image="$3"
    local snapshot_root="$4"
    local source_archive="$snapshot_root/components/volumes/$component.tar.gz"
    local rollback_archive="$WORK_DIR/pre-restore-$component.tar.gz"

    log_info "Saving pre-restore image of $component volume"
    snapshot_live_volume "$volume_name" "$helper_image" "$rollback_archive"
    RESTORED_VOLUME_COMPONENTS+=("$component")
    RESTORED_VOLUME_NAMES+=("$volume_name")
    RESTORED_VOLUME_IMAGES+=("$helper_image")

    log_info "Restoring $component volume"
    extract_live_volume "$volume_name" "$helper_image" "$source_archive"
}

restore_application_data() {
    local snapshot_root="$1"
    local -a args=()
    local component
    local matrix_sync_session_file=""
    local matrix_alert_session_file=""
    local selected=false
    for component in "${COMPONENTS[@]}"; do
        case "$component" in
            all|application|sqlite|matrix)
                args+=(--component "$component")
                selected=true
                ;;
        esac
    done
    [ "$selected" = true ] || return 0

    matrix_sync_session_file="$(container_env_value api MATRIX_SYNC_SESSION_FILE)"
    matrix_alert_session_file="$(container_env_value api MATRIX_ALERT_SESSION_FILE)"
    if [ -n "$matrix_sync_session_file" ]; then
        args+=(--matrix-state-path "$matrix_sync_session_file")
    fi
    if [ -n "$matrix_alert_session_file" ]; then
        args+=(--matrix-state-path "$matrix_alert_session_file")
    fi

    log_info "Restoring application data"
    APPLICATION_RESTORE_STARTED=true
    python3 "$DR_HELPER" restore-data \
        --snapshot-root "$snapshot_root" \
        --data-dir "$DATA_DIR" \
        --rollback-dir "$WORK_DIR/application-rollback" \
        "${args[@]}"
}

restore_qdrant() {
    local snapshot_root="$1"
    local -a import_args=()
    local rollback_archive="$WORK_DIR/pre-restore-qdrant.tar.gz"
    component_selected qdrant || return 0
    if [ -n "$QDRANT_COLLECTION" ]; then
        import_args=(--collection "$QDRANT_COLLECTION")
    else
        import_args=(--delete-absent)
    fi
    log_info "Saving pre-restore Qdrant collection snapshots"
    compose run --rm --no-deps -T \
        --user "${APP_UID:-1001}:${APP_GID:-1001}" \
        --entrypoint python api \
        -m app.scripts.disaster_recovery qdrant-export --allow-empty \
        > "$rollback_archive"
    tar -tzf "$rollback_archive" >/dev/null
    QDRANT_ROLLBACK_AVAILABLE=true

    log_info "Restoring Qdrant collection snapshots"
    compose run --rm --no-deps -T \
        --user "${APP_UID:-1001}:${APP_GID:-1001}" \
        --entrypoint python api \
        -m app.scripts.disaster_recovery qdrant-import \
        "${import_args[@]}" \
        < "$snapshot_root/components/qdrant/qdrant-snapshots.tar.gz"
}

rollback_applied_components() {
    local status=0
    local index
    local component
    local volume_name
    local helper_image

    if [ "$QDRANT_ROLLBACK_AVAILABLE" = true ]; then
        log_warning "Rolling back Qdrant collections"
        if compose run --rm --no-deps -T \
            --user "${APP_UID:-1001}:${APP_GID:-1001}" \
            --entrypoint python api \
            -m app.scripts.disaster_recovery qdrant-import --delete-absent \
            < "$WORK_DIR/pre-restore-qdrant.tar.gz"; then
            QDRANT_ROLLBACK_AVAILABLE=false
        else
            status=1
        fi
    fi

    if [ "${#RESTORED_VOLUME_COMPONENTS[@]}" -gt 0 ]; then
        for ((index=${#RESTORED_VOLUME_COMPONENTS[@]} - 1; index >= 0; index--)); do
            component="${RESTORED_VOLUME_COMPONENTS[$index]}"
            volume_name="${RESTORED_VOLUME_NAMES[$index]}"
            helper_image="${RESTORED_VOLUME_IMAGES[$index]}"
            log_warning "Rolling back $component volume"
            if ! extract_live_volume \
                "$volume_name" \
                "$helper_image" \
                "$WORK_DIR/pre-restore-$component.tar.gz"; then
                status=1
            fi
        done
    fi

    if [ "$APPLICATION_RESTORE_STARTED" = true ]; then
        log_warning "Rolling back application data"
        if python3 "$DR_HELPER" rollback-data \
            --data-dir "$DATA_DIR" \
            --rollback-dir "$WORK_DIR/application-rollback" >/dev/null; then
            APPLICATION_RESTORE_STARTED=false
        else
            status=1
        fi
    fi
    return "$status"
}

apply_restore() {
    local snapshot_root="$1"
    local helper_container
    local helper_image
    local matrix_volume=""
    local prometheus_volume=""
    local grafana_volume=""
    local bisq2_volume=""
    local alertmanager_volume=""

    if component_selected matrix \
        || component_selected prometheus \
        || component_selected grafana \
        || component_selected bisq2 \
        || component_selected alertmanager; then
        helper_container="$(container_id_for_service scheduler)"
        helper_image="$(docker inspect --format '{{.Image}}' "$helper_container")"
    fi
    if component_selected matrix; then
        matrix_volume="$(volume_for_service_path matrix-alert-relay /data)"
    fi
    if component_selected prometheus; then
        prometheus_volume="$(volume_for_service_path prometheus /prometheus)"
    fi
    if component_selected grafana; then
        grafana_volume="$(volume_for_service_path grafana /var/lib/grafana)"
    fi
    if component_selected bisq2; then
        bisq2_volume="$(volume_for_service_path bisq2-api /opt/bisq2/data)"
    fi
    if component_selected alertmanager; then
        alertmanager_volume="$(volume_for_service_path alertmanager /alertmanager)"
    fi

    stop_selected_services
    restore_application_data "$snapshot_root"
    if component_selected matrix; then
        restore_volume_archive matrix "$matrix_volume" "$helper_image" "$snapshot_root"
    fi
    if component_selected prometheus; then
        restore_volume_archive prometheus "$prometheus_volume" "$helper_image" "$snapshot_root"
    fi
    if component_selected grafana; then
        restore_volume_archive grafana "$grafana_volume" "$helper_image" "$snapshot_root"
    fi
    if component_selected bisq2; then
        restore_volume_archive bisq2 "$bisq2_volume" "$helper_image" "$snapshot_root"
    fi
    if component_selected alertmanager; then
        restore_volume_archive alertmanager "$alertmanager_volume" "$helper_image" "$snapshot_root"
    fi
    restore_qdrant "$snapshot_root"
    RESTORE_COMMITTED=true
    start_stopped_services
}

main() {
    parse_args "$@"
    initialize_paths
    validate_configuration
    umask 077
    WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/bisq-support-restore.XXXXXXXX")"
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    if [ "$APPLY" = true ]; then
        # shellcheck disable=SC3045
        exec {LOCK_FD}>"$DATA_DIR/.disaster-recovery.lock"
        if ! flock -n "$LOCK_FD"; then
            log_error "Another disaster-recovery operation is already running"
            return 1
        fi
        validate_api_data_mount
    fi

    local snapshot_root="$WORK_DIR/snapshot"
    local scratch_root="$WORK_DIR/verification"
    mkdir -p "$snapshot_root" "$scratch_root"
    decrypt_backup "$snapshot_root"
    verify_snapshot "$snapshot_root" "$scratch_root"
    verify_qdrant_in_scratch "$snapshot_root"

    if [ "$VERIFY_ONLY" = true ]; then
        log_success "Backup verified in scratch storage; no live data changed"
        return 0
    fi

    log_warning "Applying a human-approved restore of selected components"
    apply_restore "$snapshot_root"
    log_success "Selected components restored"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi

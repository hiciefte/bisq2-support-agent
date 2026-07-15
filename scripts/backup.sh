#!/bin/bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." &>/dev/null && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"
setup_colors

TARGET_DIR="${BACKUP_TARGET_DIR:-}"
MOUNT_ROOT="${BACKUP_MOUNT_ROOT:-}"
ENCRYPTION="${BACKUP_ENCRYPTION:-age}"
RECIPIENT=""
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
OFF_HOST_CONFIRMED=false
INSTALL_DIR=""
DOCKER_DIR=""
DATA_DIR=""
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
DR_HELPER=""
STAGING_DIR=""
PARTIAL_OUTPUT=""
COMPLETED_OUTPUT_NAME=""
LOCK_FD=""
declare -a QUIESCED_SERVICES=()

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
Usage: backup.sh --target DIR --mount-root DIR --confirm-off-host [options]

Create a component-consistent, encrypted disaster-recovery backup set.

Required:
  --target DIR             Mounted off-host backup target
  --mount-root DIR         Existing mounted root containing the target
  --confirm-off-host       Confirm the target is managed off this host

Encryption:
  --encryption age|gpg     Encryption implementation (default: age)
  --recipient RECIPIENT    Public age or GPG recipient

Retention:
  --retention-days DAYS    Remove completed sets older than DAYS (default: 30)

The target, mount root, recipient, encryption mode, and retention may also be
set with BACKUP_TARGET_DIR, BACKUP_MOUNT_ROOT,
BACKUP_AGE_RECIPIENT/BACKUP_GPG_RECIPIENT, BACKUP_ENCRYPTION, and
BACKUP_RETENTION_DAYS.
EOF
}

parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --target)
                [ "$#" -ge 2 ] || { log_error "--target requires a value"; return 2; }
                TARGET_DIR="$2"
                shift 2
                ;;
            --mount-root)
                [ "$#" -ge 2 ] || { log_error "--mount-root requires a value"; return 2; }
                MOUNT_ROOT="$2"
                shift 2
                ;;
            --confirm-off-host)
                OFF_HOST_CONFIRMED=true
                shift
                ;;
            --encryption)
                [ "$#" -ge 2 ] || { log_error "--encryption requires a value"; return 2; }
                ENCRYPTION="$2"
                shift 2
                ;;
            --recipient)
                [ "$#" -ge 2 ] || { log_error "--recipient requires a value"; return 2; }
                RECIPIENT="$2"
                shift 2
                ;;
            --retention-days)
                [ "$#" -ge 2 ] || { log_error "--retention-days requires a value"; return 2; }
                RETENTION_DAYS="$2"
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

service_is_running() {
    local running_services
    running_services="$(compose ps --status running --services)" || return 2
    grep -Fxq "$1" <<< "$running_services"
}

resume_services() {
    if [ "${#QUIESCED_SERVICES[@]}" -eq 0 ]; then
        return 0
    fi
    log_info "Restarting quiesced services"
    if ! compose start "${QUIESCED_SERVICES[@]}" >/dev/null; then
        log_error "Could not restart every quiesced service"
        return 1
    fi
    QUIESCED_SERVICES=()
}

cleanup() {
    local exit_code=$?
    set +e
    resume_services
    if [ -n "$PARTIAL_OUTPUT" ] && [ -e "$PARTIAL_OUTPUT" ]; then
        rm -f -- "$PARTIAL_OUTPUT"
    fi
    if [ -n "$STAGING_DIR" ] && [ -d "$STAGING_DIR" ]; then
        rm -rf -- "$STAGING_DIR"
    fi
    if [ -n "$LOCK_FD" ]; then
        flock -u "$LOCK_FD"
    fi
    exit "$exit_code"
}

quiesce_services() {
    local service
    local status
    for service in scheduler api alertmanager matrix-alert-relay grafana prometheus bisq2-api; do
        if service_is_running "$service"; then
            log_info "Quiescing $service"
            QUIESCED_SERVICES+=("$service")
            compose stop --timeout 30 "$service" >/dev/null
        else
            status=$?
            if [ "$status" -ne 1 ]; then
                log_error "Could not determine whether $service is running"
                return "$status"
            fi
        fi
    done
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

snapshot_volume() {
    local component="$1"
    local volume_name="$2"
    local helper_image="$3"
    local destination="$STAGING_DIR/components/volumes/$component.tar.gz"
    local raw_archive="$STAGING_DIR/components/volumes/.$component.raw.tar.gz"

    log_info "Snapshotting $component volume"
    docker run --rm \
        --network none \
        --read-only \
        --user 0:0 \
        --cap-drop ALL \
        --cap-add DAC_READ_SEARCH \
        --security-opt no-new-privileges \
        --volume "$volume_name:/source:ro" \
        --entrypoint tar \
        "$helper_image" -C /source -czf - . > "$raw_archive"
    tar -tzf "$raw_archive" >/dev/null
    python3 "$DR_HELPER" normalize-volume \
        --input "$raw_archive" \
        --output "$destination" >/dev/null
    rm -f -- "$raw_archive"
    tar -tzf "$destination" >/dev/null
}

validate_configuration() {
    [ -n "$TARGET_DIR" ] || { log_error "An off-host backup target is required"; return 2; }
    [ -n "$MOUNT_ROOT" ] || { log_error "An off-host mount root is required"; return 2; }
    [ "$OFF_HOST_CONFIRMED" = true ] || {
        log_error "Pass --confirm-off-host after verifying the target is off-host"
        return 2
    }
    [[ "$RETENTION_DAYS" =~ ^[1-9][0-9]*$ ]] || {
        log_error "Retention days must be a positive integer"
        return 2
    }
    case "$ENCRYPTION" in
        age)
            RECIPIENT="${RECIPIENT:-${BACKUP_AGE_RECIPIENT:-}}"
            [ -n "$RECIPIENT" ] || { log_error "An age recipient is required"; return 2; }
            check_required_commands age || return 1
            ;;
        gpg)
            RECIPIENT="${RECIPIENT:-${BACKUP_GPG_RECIPIENT:-}}"
            [ -n "$RECIPIENT" ] || { log_error "A GPG recipient is required"; return 2; }
            check_required_commands gpg || return 1
            ;;
        *)
            log_error "Encryption must be age or gpg"
            return 2
            ;;
    esac

    check_required_commands docker flock python3 tar find grep rm mktemp mountpoint || return 1
    check_docker_daemon || return 1
    check_docker_compose || return 1
    [ -f "$DR_HELPER" ] || { log_error "Disaster-recovery helper is missing"; return 1; }
    [ -d "$DATA_DIR" ] || { log_error "Application data directory is missing"; return 1; }
    [ -f "$DOCKER_DIR/.env" ] || { log_error "Docker environment file is missing"; return 1; }

    [ -d "$MOUNT_ROOT" ] && [ ! -L "$MOUNT_ROOT" ] || {
        log_error "Off-host mount root is missing or unsafe"
        return 1
    }
    MOUNT_ROOT="$(cd "$MOUNT_ROOT" && pwd -P)"
    [ "$MOUNT_ROOT" != / ] && mountpoint -q -- "$MOUNT_ROOT" || {
        log_error "Off-host mount root is not mounted"
        return 1
    }
    [ -d "$TARGET_DIR" ] && [ ! -L "$TARGET_DIR" ] || {
        log_error "Backup target is missing or unsafe"
        return 1
    }
    TARGET_DIR="$(cd "$TARGET_DIR" && pwd -P)"
    case "$TARGET_DIR/" in
        "$MOUNT_ROOT/"*) ;;
        *)
            log_error "Backup target must be inside the verified mount root"
            return 2
            ;;
    esac
    case "$TARGET_DIR/" in
        "$INSTALL_DIR/"*)
            log_error "Backup target must not be inside the installation tree"
            return 2
            ;;
    esac
    [ -w "$TARGET_DIR" ] || { log_error "Backup target is not writable"; return 1; }
}

encrypt_backup() {
    local timestamp="$1"
    local extension
    local filename

    if [ "$ENCRYPTION" = age ]; then
        extension="age"
    else
        extension="gpg"
    fi
    filename="bisq-support-backup-$timestamp.tar.gz.$extension"
    PARTIAL_OUTPUT="$TARGET_DIR/.$filename.partial.$$"

    log_info "Encrypting backup set" >&2
    if [ "$ENCRYPTION" = age ]; then
        tar -C "$STAGING_DIR" -czf - . | \
            age --recipient "$RECIPIENT" --output "$PARTIAL_OUTPUT"
    else
        tar -C "$STAGING_DIR" -czf - . | \
            gpg --batch --yes --trust-model always \
                --recipient "$RECIPIENT" --output "$PARTIAL_OUTPUT" --encrypt
    fi
    chmod 600 "$PARTIAL_OUTPUT"
    mv -- "$PARTIAL_OUTPUT" "$TARGET_DIR/$filename"
    PARTIAL_OUTPUT=""
    COMPLETED_OUTPUT_NAME="$filename"
}

apply_retention() {
    log_info "Applying backup retention"
    find "$TARGET_DIR" -maxdepth 1 -type f \
        \( -name 'bisq-support-backup-*.tar.gz.age' \
        -o -name 'bisq-support-backup-*.tar.gz.gpg' \) \
        -mtime "+$RETENTION_DAYS" -delete
}

main() {
    parse_args "$@"
    initialize_paths
    validate_configuration
    umask 077

    # shellcheck disable=SC3045
    exec {LOCK_FD}>"$DATA_DIR/.disaster-recovery.lock"
    if ! flock -n "$LOCK_FD"; then
        log_error "Another disaster-recovery operation is already running"
        return 1
    fi
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    local helper_container
    local helper_image
    local matrix_volume
    local prometheus_volume
    local grafana_volume
    local bisq2_volume
    local alertmanager_volume
    local timestamp
    local matrix_sync_session_file
    local matrix_alert_session_file
    local -a matrix_snapshot_args=(--env-file "$DOCKER_DIR/.env")

    validate_api_data_mount
    helper_container="$(container_id_for_service scheduler)"
    helper_image="$(docker inspect --format '{{.Image}}' "$helper_container")"
    matrix_volume="$(volume_for_service_path matrix-alert-relay /data)"
    prometheus_volume="$(volume_for_service_path prometheus /prometheus)"
    grafana_volume="$(volume_for_service_path grafana /var/lib/grafana)"
    bisq2_volume="$(volume_for_service_path bisq2-api /opt/bisq2/data)"
    alertmanager_volume="$(volume_for_service_path alertmanager /alertmanager)"
    matrix_sync_session_file="$(container_env_value api MATRIX_SYNC_SESSION_FILE)"
    matrix_alert_session_file="$(container_env_value api MATRIX_ALERT_SESSION_FILE)"
    if [ -n "$matrix_sync_session_file" ]; then
        matrix_snapshot_args+=(--matrix-state-path "$matrix_sync_session_file")
    fi
    if [ -n "$matrix_alert_session_file" ]; then
        matrix_snapshot_args+=(--matrix-state-path "$matrix_alert_session_file")
    fi

    STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/bisq-support-backup.XXXXXXXX")"
    mkdir -p "$STAGING_DIR/components/qdrant" "$STAGING_DIR/components/volumes" "$STAGING_DIR/manifest"

    quiesce_services

    log_info "Creating Qdrant collection snapshots"
    compose run --rm --no-deps -T \
        --user "${APP_UID:-1001}:${APP_GID:-1001}" \
        --entrypoint python api \
        -m app.scripts.disaster_recovery qdrant-export \
        > "$STAGING_DIR/components/qdrant/qdrant-snapshots.tar.gz"
    tar -tzf "$STAGING_DIR/components/qdrant/qdrant-snapshots.tar.gz" >/dev/null

    log_info "Snapshotting application and Matrix state"
    python3 "$DR_HELPER" snapshot-data \
        --data-dir "$DATA_DIR" \
        "${matrix_snapshot_args[@]}" \
        --output-dir "$STAGING_DIR" >/dev/null

    snapshot_volume matrix "$matrix_volume" "$helper_image"
    snapshot_volume prometheus "$prometheus_volume" "$helper_image"
    snapshot_volume grafana "$grafana_volume" "$helper_image"
    snapshot_volume bisq2 "$bisq2_volume" "$helper_image"
    snapshot_volume alertmanager "$alertmanager_volume" "$helper_image"

    resume_services

    log_info "Building value-free configuration inventory and manifest"
    python3 "$DR_HELPER" create-manifest \
        --root "$STAGING_DIR" \
        --env-file "$DOCKER_DIR/.env" >/dev/null

    timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    encrypt_backup "$timestamp"
    apply_retention
    log_success "Encrypted backup completed: $COMPLETED_OUTPUT_NAME"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi

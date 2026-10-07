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
EXPORT_DIR=""
BACKUP_RECEIPT=""
INSTALL_DIR=""
DOCKER_DIR=""
DATA_DIR=""
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
DR_HELPER=""
STAGING_DIR=""
PARTIAL_OUTPUT=""
COMPLETED_OUTPUT_NAME=""
LOCK_FD=""
LOCK_FD_BORROWED=false
RECOVERY_CONTROL_DIR=""
RECOVERY_FAILURE_MARKER=""
RECOVERY_LOCK_FILE=""
EXPECTED_MOUNT_IDENTITY=""
EXPECTED_TARGET_IDENTITY=""
BACKUP_TARGET_IDENTITY_CAPTURED=false
WRITER_METADATA_DIR=""
RESUME_STATE=not_attempted
CAPTURE_COMPLETE=false
BACKUP_COMPLETED=false
PRESERVED_PAUSED_SCHEDULER=false
declare -a QUIESCED_SERVICES=()

initialize_paths() {
    source_deploy_paths >&2 || true
    INSTALL_DIR="${BISQ_SUPPORT_INSTALL_DIR:-$PROJECT_ROOT}"
    INSTALL_DIR="$(cd "$INSTALL_DIR" && pwd -P)"
    DOCKER_DIR="$INSTALL_DIR/docker"
    DATA_DIR="$INSTALL_DIR/api/data"
    # Use the helper from the reviewed script source. During the one-time
    # release-gate transition the script runs from a detached candidate
    # worktree while INSTALL_DIR still points at the older production checkout.
    DR_HELPER="$PROJECT_ROOT/api/app/scripts/disaster_recovery.py"
    RECOVERY_CONTROL_DIR="$INSTALL_DIR/failed_updates/disaster-recovery"
    RECOVERY_FAILURE_MARKER="$RECOVERY_CONTROL_DIR/recovery-blocked"
    RECOVERY_LOCK_FILE="$RECOVERY_CONTROL_DIR/recovery.lock"
}

usage() {
    cat <<'EOF'
Usage: backup.sh --target DIR --mount-root DIR --confirm-off-host [options]

Create a component-consistent, encrypted disaster-recovery backup set.
Alternatively: backup.sh --export-dir DIR [encryption options]
An export is same-host ciphertext only; it is NOT an off-host backup.
  --receipt FILE           Exclusive success receipt after writer/scratch cleanup

Required:
  --target DIR             Mounted off-host backup target
  --mount-root DIR         Existing mounted root containing the target
  --confirm-off-host       Confirm the target is managed off this host

Encryption:
  --encryption age|gpg     Encryption implementation (default: age)
  --recipient RECIPIENT    Public age recipient or full GPG fingerprint

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
            --export-dir)
                [ "$#" -ge 2 ] || return 2
                EXPORT_DIR="$2"
                shift 2
                ;;
            --receipt)
                [ "$#" -ge 2 ] || return 2
                BACKUP_RECEIPT="$2"
                shift 2
                ;;
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

service_is_configured() {
    local configured_services
    configured_services="$(compose config --services)" || return 2
    grep -Fxq "$1" <<< "$configured_services"
}

prepare_writer_metadata() {
    if [ -n "$WRITER_METADATA_DIR" ] || [ -z "$STAGING_DIR" ] \
        || [ ! -d "$STAGING_DIR" ] || [ -L "$STAGING_DIR" ]; then
        log_error "Backup writer metadata directory is unavailable or already used"
        return 1
    fi
    # Full Config includes environment values, which must never enter a backup
    # archive. Keep private evidence beside (not inside) the snapshot payload.
    WRITER_METADATA_DIR="$STAGING_DIR.writer-identities"
    (umask 077; mkdir -m 700 -- "$WRITER_METADATA_DIR") || return 1
}

capture_writer_identity() {
    local service="$1"
    local phase="$2"
    local container_id
    local destination="$WRITER_METADATA_DIR/$service.$phase"
    local format='{"Id":{{json .Id}},"Image":{{json .Image}},"Created":{{json .Created}},"Config":{{json .Config}},"Mounts":{{json .Mounts}}}'

    container_id="$(container_id_for_service "$service")" || return 1
    if [[ ! "$container_id" =~ ^[0-9a-f]{64}$ ]]; then
        log_error "Backup writer container identity is invalid: $service"
        return 1
    fi
    # Inspect may contain credentials. Keep the full evidence private and never
    # put it in command arguments, logs, or the digest helper's error output.
    (
        umask 077
        set -o noclobber
        printf '%s\n' "$container_id" > "$destination.id" || exit 1
        docker inspect --format "$format" "$container_id" > "$destination.json" || exit 1
        python3 "$SCRIPT_DIR/lib/docker_identity.py" "$container_id" \
            < "$destination.json" > "$destination.sha256"
    ) || return 1
}

verify_writer_identity() {
    local service="$1"
    local phase="$2"
    capture_writer_identity "$service" "$phase" || return 1
    if ! cmp -s "$WRITER_METADATA_DIR/$service.before.id" \
        "$WRITER_METADATA_DIR/$service.$phase.id" \
        || ! cmp -s "$WRITER_METADATA_DIR/$service.before.sha256" \
            "$WRITER_METADATA_DIR/$service.$phase.sha256"; then
        log_error "Backup writer identity changed: $service"
        return 1
    fi
}

verify_writer_running() {
    local service="$1"
    local container_id
    local destination="$WRITER_METADATA_DIR/$service.after-state.json"
    local format='{"Id":{{json .Id}},"Running":{{json .State.Running}},"Paused":{{json .State.Paused}},"Restarting":{{json .State.Restarting}},"Pid":{{json .State.Pid}}}'
    container_id="$(cat "$WRITER_METADATA_DIR/$service.before.id")" || return 1
    (
        umask 077
        set -o noclobber
        docker inspect --format "$format" "$container_id" > "$destination" || exit 1
        python3 - "$container_id" "$destination" <<'PY'
import json
import sys

try:
    with open(sys.argv[2], "rb") as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError
    state = json.loads(raw)
    valid = (
        isinstance(state, dict)
        and set(state) == {"Id", "Running", "Paused", "Restarting", "Pid"}
        and state["Id"] == sys.argv[1]
        and state["Running"] is True
        and state["Paused"] is False
        and state["Restarting"] is False
        and type(state["Pid"]) is int
        and state["Pid"] > 0
    )
except (OSError, ValueError, TypeError):
    valid = False
sys.exit(0 if valid else 1)
PY
    ) || {
        log_error "Backup writer did not resume running: $service"
        return 1
    }
}

scheduler_pause_state() {
    local phase="$1"
    local container_id="$2"
    local destination="$WRITER_METADATA_DIR/scheduler.pause-$phase.json"
    local format='{"Id":{{json .Id}},"Running":{{json .State.Running}},"Paused":{{json .State.Paused}},"Restarting":{{json .State.Restarting}},"Pid":{{json .State.Pid}},"StartedAt":{{json .State.StartedAt}}}'
    (
        umask 077
        set -o noclobber
        docker inspect --format "$format" "$container_id" > "$destination" || exit 1
        python3 - "$container_id" "$destination" "$phase" \
            "$WRITER_METADATA_DIR/scheduler.pause-before.json" <<'PY'
import json
import sys

try:
    with open(sys.argv[2], "rb") as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError
    state = json.loads(raw)
    if not (
        isinstance(state, dict)
        and set(state) == {"Id", "Running", "Paused", "Restarting", "Pid", "StartedAt"}
        and state["Id"] == sys.argv[1]
        and all(type(state[key]) is bool for key in ("Running", "Paused", "Restarting"))
        and type(state["Pid"]) is int
        and state["Pid"] >= 0
        and isinstance(state["StartedAt"], str)
        and state["StartedAt"]
    ):
        raise ValueError
    if state["Paused"] and not (
        state["Running"] and not state["Restarting"] and state["Pid"] > 0
    ):
        raise ValueError
    if sys.argv[3] != "before":
        with open(sys.argv[4], "rb") as stream:
            before = json.load(stream)
        if not state["Paused"] or state != before:
            raise ValueError
except (OSError, ValueError, TypeError):
    sys.exit(1)
print("paused" if state["Paused"] else "not_paused")
PY
    )
}

observe_paused_scheduler() {
    local container_id
    local state
    container_id="$(compose ps --all -q scheduler)" || return 1
    # Preserve legacy absence behavior; main independently requires its helper
    # container. Observation grants no authority to pause or unpause anything.
    [ -n "$container_id" ] || return 0
    [[ "$container_id" =~ ^[0-9a-f]{64}$ ]] || return 1
    state="$(scheduler_pause_state before "$container_id")" || return 1
    if [ "$state" = paused ]; then
        capture_writer_identity scheduler before || return 1
        if [ "$(cat "$WRITER_METADATA_DIR/scheduler.before.id")" != "$container_id" ]; then
            log_error "Scheduler changed during initial pause observation"
            return 1
        fi
        PRESERVED_PAUSED_SCHEDULER=true
    fi
}

verify_preserved_scheduler() {
    local phase="$1"
    local container_id
    [ "$PRESERVED_PAUSED_SCHEDULER" = true ] || return 0
    container_id="$(cat "$WRITER_METADATA_DIR/scheduler.before.id")" || return 1
    verify_writer_identity scheduler "$phase" || return 1
    if ! scheduler_pause_state "$phase" "$container_id" >/dev/null; then
        log_error "Paused scheduler changed during backup; leaving its state untouched"
        return 1
    fi
}

resume_services() {
    local service
    local resume_status=0
    local identity_status=0
    if [ "${#QUIESCED_SERVICES[@]}" -eq 0 ]; then
        return 0
    fi
    if [ "$RESUME_STATE" != not_attempted ]; then
        log_error "Backup writer resume was already attempted; refusing a retry"
        return 1
    fi
    # Set before every check and effect: an interrupted or failed start must not
    # be repeated by the EXIT trap, even if some writers are still stopped.
    RESUME_STATE=attempted
    if ! verify_preserved_scheduler resume; then
        RESUME_STATE=failed
        return 1
    fi
    for service in "${QUIESCED_SERVICES[@]}"; do
        if ! verify_writer_identity "$service" resume; then
            RESUME_STATE=failed
            return 1
        fi
    done
    log_info "Restarting quiesced services"
    compose start "${QUIESCED_SERVICES[@]}" >/dev/null || resume_status=$?
    # A failed Compose start may have resumed a subset. Inspect once even after
    # failure, retaining the actual identities instead of retrying the start.
    for service in "${QUIESCED_SERVICES[@]}"; do
        verify_writer_identity "$service" after || identity_status=1
        verify_writer_running "$service" || identity_status=1
    done
    verify_preserved_scheduler after || identity_status=1
    if [ "$resume_status" -ne 0 ] || [ "$identity_status" -ne 0 ]; then
        RESUME_STATE=failed
        log_error "Could not verify every quiesced service resumed unchanged"
        return 1
    fi
    RESUME_STATE=succeeded
    QUIESCED_SERVICES=()
}

cleanup() {
    local exit_code=$?
    local cleanup_status
    trap - EXIT
    set +e
    resume_services
    cleanup_status=$?
    if [ "$cleanup_status" -ne 0 ] && [ "$exit_code" -eq 0 ]; then
        exit_code="$cleanup_status"
    fi
    verify_preserved_scheduler final
    cleanup_status=$?
    if [ "$cleanup_status" -ne 0 ] && [ "$exit_code" -eq 0 ]; then
        exit_code="$cleanup_status"
    fi
    if [ "$exit_code" -eq 0 ] && [ "$BACKUP_COMPLETED" != true ]; then
        exit_code=1
    fi
    if [ "$exit_code" -eq 0 ] && [ -n "$PARTIAL_OUTPUT" ]; then
        exit_code=1
    fi
    if [ -n "$STAGING_DIR" ] && [ -d "$STAGING_DIR" ]; then
        if [ "$exit_code" -eq 0 ]; then
            rm -rf -- "$STAGING_DIR"
            cleanup_status=$?
            if [ "$cleanup_status" -ne 0 ]; then
                exit_code="$cleanup_status"
            fi
        else
            # Both complete and incomplete snapshots remain private evidence.
            # Neither this record nor a partial ciphertext claims a valid backup.
            (
                umask 077
                set -o noclobber
                printf 'capture_complete=%s\nresume_state=%s\nexit_code=%s\n' \
                    "$CAPTURE_COMPLETE" "$RESUME_STATE" "$exit_code" \
                    > "$STAGING_DIR/backup-failure.state"
            )
            log_error "Backup failed; private staging retained at $STAGING_DIR"
        fi
    fi
    if [ -n "$WRITER_METADATA_DIR" ] && [ -d "$WRITER_METADATA_DIR" ]; then
        if [ "$exit_code" -eq 0 ]; then
            rm -rf -- "$WRITER_METADATA_DIR"
            cleanup_status=$?
            if [ "$cleanup_status" -ne 0 ]; then
                exit_code="$cleanup_status"
            fi
        else
            log_error "Private writer metadata retained at $WRITER_METADATA_DIR"
        fi
    fi
    # Never remove a partial ciphertext after failure. Its off-host target may
    # have changed, and the bytes are useful for read-only reconciliation.
    if [ -n "$PARTIAL_OUTPUT" ]; then
        log_error "Incomplete encrypted backup retained for reconciliation"
    fi
    if [ -n "$LOCK_FD" ] && [ "$LOCK_FD_BORROWED" = false ]; then
        flock -u "$LOCK_FD"
        cleanup_status=$?
        if [ "$cleanup_status" -ne 0 ] && [ "$exit_code" -eq 0 ]; then
            exit_code="$cleanup_status"
        fi
    fi
    if [ "$exit_code" -eq 0 ] && [ -n "$BACKUP_RECEIPT" ]; then
        write_backup_receipt || exit_code=1
    fi
    exit "$exit_code"
}

write_backup_receipt() {
    revalidate_backup_target || return 1
    python3 - "$BACKUP_RECEIPT" "$TARGET_DIR/$COMPLETED_OUTPUT_NAME" "$EXPORT_DIR" <<'PYRECEIPT'
import hashlib, json, os, pathlib, stat, sys
receipt, ciphertext, export = sys.argv[1:]
p = pathlib.Path(ciphertext)
fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
with os.fdopen(fd, 'rb') as f:
    st = os.fstat(f.fileno())
    assert stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_size > 0
    sha = hashlib.file_digest(f, 'sha256').hexdigest()
record = {'schema': 'canonical-backup-v1', 'ciphertext_name': p.name,
          'ciphertext_sha256': sha, 'ciphertext_bytes': st.st_size,
          'destination_kind': 'same_host_encrypted_export' if export else 'mounted_off_host',
          'writers_resumed': True, 'scratch_cleanup_verified': True}
fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, 'w') as f:
    json.dump(record, f, sort_keys=True, separators=(',', ':')); f.write('\n')
    f.flush(); os.fsync(f.fileno())
fd = os.open(pathlib.Path(receipt).parent, os.O_RDONLY)
try: os.fsync(fd)
finally: os.close(fd)
PYRECEIPT
}

recovery_control_path_is_safe() {
    if [ -L "$INSTALL_DIR/failed_updates" ] \
        || [ -L "$RECOVERY_CONTROL_DIR" ] \
        || [ -L "$RECOVERY_FAILURE_MARKER" ] \
        || [ -L "$RECOVERY_LOCK_FILE" ]; then
        log_error "Disaster-recovery control path is unsafe"
        return 1
    fi
    if [ -e "$RECOVERY_LOCK_FILE" ] && [ ! -f "$RECOVERY_LOCK_FILE" ]; then
        log_error "Disaster-recovery lock path is unsafe"
        return 1
    fi
}

ensure_recovery_not_blocked() {
    recovery_control_path_is_safe || return 1
    local lock_state=""
    if [ -f "$RECOVERY_LOCK_FILE" ]; then
        IFS= read -r lock_state < "$RECOVERY_LOCK_FILE" || true
    fi
    if [ -e "$RECOVERY_FAILURE_MARKER" ] || [ "$lock_state" = blocked ]; then
        log_error "Disaster recovery is blocked after an unresolved recovery failure"
        log_error "Inspect the preserved recovery state, then use restore.sh to clear the block"
        return 1
    fi
}

open_recovery_lock() {
    # Record the caller's ownership before common.sh exports a newly acquired
    # descriptor. An invalid inherited proof must not fall back to acquisition.
    if [ -n "${BISQ_SUPPORT_LIFECYCLE_LOCK_FD:-}" ]; then
        LOCK_FD_BORROWED=true
    fi
    acquire_production_lifecycle_lock "$INSTALL_DIR" || return 1
    LOCK_FD="$BISQ_SUPPORT_LIFECYCLE_LOCK_FD"
}

acquire_recovery_lock() {
    open_recovery_lock || return 1
    ensure_recovery_not_blocked || return 1
}

path_identity() {
    stat -Lc '%d:%i' -- "$1" 2>/dev/null \
        || stat -Lf '%d:%i' -- "$1" 2>/dev/null
}

capture_backup_target_identity() {
    if [ -z "$EXPORT_DIR" ]; then
    EXPECTED_MOUNT_IDENTITY="$(mountpoint -d -- "$MOUNT_ROOT")" || {
        log_error "Could not capture the off-host mount identity"
        return 1
    }
    else
        EXPECTED_MOUNT_IDENTITY=private-export
    fi
    EXPECTED_TARGET_IDENTITY="$(path_identity "$TARGET_DIR")" || {
        log_error "Could not capture the backup target identity"
        return 1
    }
    if [ -z "$EXPECTED_MOUNT_IDENTITY" ] || [ -z "$EXPECTED_TARGET_IDENTITY" ]; then
        log_error "Off-host backup identity is empty"
        return 1
    fi
    BACKUP_TARGET_IDENTITY_CAPTURED=true
}

revalidate_backup_target() {
    local current_mount_identity
    local current_target_identity
    local current_target

    # Direct function-level tests may call encryption without the main entrypoint.
    # The executable path always captures identities before snapshot work begins.
    if [ "$BACKUP_TARGET_IDENTITY_CAPTURED" != true ]; then
        return 0
    fi
    if [ -z "$EXPORT_DIR" ]; then
    if [ ! -d "$MOUNT_ROOT" ] || [ -L "$MOUNT_ROOT" ] \
        || ! mountpoint -q -- "$MOUNT_ROOT"; then
        log_error "Off-host mount is no longer available"
        return 1
    fi
    current_mount_identity="$(mountpoint -d -- "$MOUNT_ROOT")" || {
        log_error "Could not revalidate the off-host mount identity"
        return 1
    }
    if [ "$current_mount_identity" != "$EXPECTED_MOUNT_IDENTITY" ]; then
        log_error "Off-host mount identity changed during backup"
        return 1
    fi
    fi
    if [ ! -d "$TARGET_DIR" ] || [ -L "$TARGET_DIR" ]; then
        log_error "Backup target is no longer available or safe"
        return 1
    fi
    current_target="$(cd "$TARGET_DIR" && pwd -P)" || {
        log_error "Could not revalidate the backup target path"
        return 1
    }
    if [ "$current_target" != "$TARGET_DIR" ]; then
        log_error "Backup target path changed during backup"
        return 1
    fi
    current_target_identity="$(path_identity "$TARGET_DIR")" || {
        log_error "Could not revalidate the backup target identity"
        return 1
    }
    if [ "$current_target_identity" != "$EXPECTED_TARGET_IDENTITY" ]; then
        log_error "Backup target identity changed during backup"
        return 1
    fi
}

quiesce_services() {
    local service
    local status
    prepare_writer_metadata || return 1
    observe_paused_scheduler || return 1
    for service in scheduler api alertmanager matrix-alert-relay grafana prometheus bisq2-api; do
        if [ "$service" = scheduler ] && [ "$PRESERVED_PAUSED_SCHEDULER" = true ]; then
            continue
        fi
        if service_is_running "$service"; then
            capture_writer_identity "$service" before || return 1
            log_info "Quiescing $service"
            QUIESCED_SERVICES+=("$service")
            compose stop --timeout 30 "$service" >/dev/null || return 1
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

snapshot_absent_volume() {
    local component="$1"
    local destination="$STAGING_DIR/components/volumes/$component.tar.gz"

    log_warning "Recording absent legacy $component volume"
    tar -czf "$destination" -T /dev/null
    tar -tzf "$destination" >/dev/null
}

validate_gpg_recipient_fingerprint() {
    local normalized_recipient
    local key_listing
    local fingerprint
    local normalized_fingerprint
    local exact_match_count=0
    local -a key_fields=()

    if [[ ! "$RECIPIENT" =~ ^[0-9A-Fa-f]{40}$ ]] \
        && [[ ! "$RECIPIENT" =~ ^[0-9A-Fa-f]{64}$ ]]; then
        log_error "The GPG recipient must be a full 40- or 64-character fingerprint"
        return 2
    fi

    normalized_recipient="$(
        printf '%s' "$RECIPIENT" | LC_ALL=C tr '[:lower:]' '[:upper:]'
    )"
    if ! key_listing="$(
        gpg --batch --with-colons --fingerprint --list-keys \
            -- "$normalized_recipient" 2>/dev/null
    )"; then
        log_error "The GPG recipient fingerprint is not present in the public keyring"
        return 2
    fi

    while IFS=: read -r -a key_fields; do
        if [ "${key_fields[0]:-}" != fpr ]; then
            continue
        fi
        fingerprint="${key_fields[9]:-}"
        normalized_fingerprint="$(
            printf '%s' "$fingerprint" | LC_ALL=C tr '[:lower:]' '[:upper:]'
        )"
        if [ "$normalized_fingerprint" = "$normalized_recipient" ]; then
            exact_match_count=$((exact_match_count + 1))
        fi
    done <<< "$key_listing"

    if [ "$exact_match_count" -eq 0 ]; then
        log_error "The GPG recipient fingerprint has no exact public-key match"
        return 2
    fi
    if [ "$exact_match_count" -ne 1 ]; then
        log_error "The GPG recipient fingerprint resolves ambiguously"
        return 2
    fi
    RECIPIENT="$normalized_recipient"
}

validate_configuration() {
    if [ -n "$BACKUP_RECEIPT" ] && { [ -e "$BACKUP_RECEIPT" ] || [ -L "$BACKUP_RECEIPT" ]; }; then
        log_error "Backup receipt already exists; reconcile instead of retrying"
        return 2
    fi
    if [ -n "$EXPORT_DIR" ]; then
        if [ -n "$TARGET_DIR" ] || [ -n "$MOUNT_ROOT" ] || [ "$OFF_HOST_CONFIRMED" != false ]; then
            log_error "Private export and mounted off-host options are mutually exclusive"
            return 2
        fi
        TARGET_DIR="$EXPORT_DIR"
    else
    [ -n "$TARGET_DIR" ] || { log_error "An off-host backup target is required"; return 2; }
    [ -n "$MOUNT_ROOT" ] || { log_error "An off-host mount root is required"; return 2; }
    [ "$OFF_HOST_CONFIRMED" = true ] || {
        log_error "Pass --confirm-off-host after verifying the target is off-host"
        return 2
    }
    fi
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
            check_required_commands gpg tr || return 1
            validate_gpg_recipient_fingerprint || return $?
            ;;
        *)
            log_error "Encryption must be age or gpg"
            return 2
            ;;
    esac

    check_required_commands docker flock python3 tar find grep rm mv ln mktemp mountpoint stat || return 1
    check_docker_daemon || return 1
    check_docker_compose || return 1
    [ -f "$DR_HELPER" ] || { log_error "Disaster-recovery helper is missing"; return 1; }
    [ -d "$DATA_DIR" ] || { log_error "Application data directory is missing"; return 1; }
    [ -f "$DOCKER_DIR/.env" ] || { log_error "Docker environment file is missing"; return 1; }

    if [ -z "$EXPORT_DIR" ]; then
    if [ ! -d "$MOUNT_ROOT" ] || [ -L "$MOUNT_ROOT" ]; then
        log_error "Off-host mount root is missing or unsafe"
        return 1
    fi
    MOUNT_ROOT="$(cd "$MOUNT_ROOT" && pwd -P)"
    if [ "$MOUNT_ROOT" = / ] || ! mountpoint -q -- "$MOUNT_ROOT"; then
        log_error "Off-host mount root is not mounted"
        return 1
    fi
    fi
    if [ ! -d "$TARGET_DIR" ] || [ -L "$TARGET_DIR" ]; then
        log_error "Backup target is missing or unsafe"
        return 1
    fi
    TARGET_DIR="$(cd "$TARGET_DIR" && pwd -P)"
    if [ -z "$EXPORT_DIR" ]; then
    case "$TARGET_DIR/" in
        "$MOUNT_ROOT/"*) ;;
        *)
            log_error "Backup target must be inside the verified mount root"
            return 2
            ;;
    esac
    else
        python3 - "$TARGET_DIR" <<'PYPRIVATE'
import os, stat, sys
s = os.stat(sys.argv[1], follow_symlinks=False)
assert stat.S_ISDIR(s.st_mode) and s.st_uid == os.geteuid() and stat.S_IMODE(s.st_mode) == 0o700
PYPRIVATE
    fi
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
    revalidate_backup_target || return 1
    PARTIAL_OUTPUT="$TARGET_DIR/.$filename.partial.$$"

    log_info "Encrypting backup set" >&2
    if [ "$ENCRYPTION" = age ]; then
        if ! (umask 077; tar -C "$STAGING_DIR" -czf - . | \
            age --recipient "$RECIPIENT" --output "$PARTIAL_OUTPUT"); then
            return 1
        fi
    else
        if ! (umask 077; tar -C "$STAGING_DIR" -czf - . | \
            gpg --batch --yes \
                --recipient "$RECIPIENT" --output "$PARTIAL_OUTPUT" --encrypt); then
            return 1
        fi
    fi
    revalidate_backup_target || return 1
    chmod 600 "$PARTIAL_OUTPUT" || return 1
    revalidate_backup_target || return 1
    ln -- "$PARTIAL_OUTPUT" "$TARGET_DIR/$filename" || return 1
    rm -- "$PARTIAL_OUTPUT" || return 1
    PARTIAL_OUTPUT=""
    COMPLETED_OUTPUT_NAME="$filename"
}

apply_retention() {
    # Deployment exports have an explicit copy/restore lifecycle, no age deletion.
    [ -z "$EXPORT_DIR" ] || return 0
    revalidate_backup_target || return 1
    log_info "Applying backup retention"
    find "$TARGET_DIR" -maxdepth 1 -type f \
        \( -name 'bisq-support-backup-*.tar.gz.age' \
        -o -name 'bisq-support-backup-*.tar.gz.gpg' \) \
        -mtime "+$RETENTION_DAYS" -delete
}

main() {
    parse_args "$@"
    initialize_paths
    umask 077
    ensure_recovery_not_blocked
    validate_configuration
    capture_backup_target_identity

    acquire_recovery_lock
    pin_existing_compose_project \
        "$DOCKER_DIR" "$COMPOSE_FILE" existing || return 1
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    local helper_container
    local helper_image
    local matrix_volume
    local matrix_volume_absent=false
    local prometheus_volume
    local grafana_volume
    local bisq2_volume
    local alertmanager_volume
    local timestamp
    local matrix_sync_session_file
    local matrix_alert_session_file
    local status
    local -a matrix_snapshot_args=(--env-file "$DOCKER_DIR/.env")
    local -a absent_volume_args=()

    validate_api_data_mount
    helper_container="$(container_id_for_service scheduler)"
    helper_image="$(docker inspect --format '{{.Image}}' "$helper_container")"
    if service_is_configured matrix-alert-relay; then
        matrix_volume="$(volume_for_service_path matrix-alert-relay /data)"
    else
        status=$?
        if [ "$status" -ne 1 ]; then
            log_error "Could not inspect the Matrix relay service topology"
            return "$status"
        fi
        matrix_volume_absent=true
        absent_volume_args+=(--absent-volume-component matrix)
    fi
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
        --volume "$DR_HELPER:/app/app/scripts/disaster_recovery.py:ro" \
        --entrypoint python api \
        -m app.scripts.disaster_recovery qdrant-export \
        > "$STAGING_DIR/components/qdrant/qdrant-snapshots.tar.gz"
    tar -tzf "$STAGING_DIR/components/qdrant/qdrant-snapshots.tar.gz" >/dev/null

    log_info "Snapshotting application and Matrix state"
    python3 "$DR_HELPER" snapshot-data \
        --data-dir "$DATA_DIR" \
        "${matrix_snapshot_args[@]}" \
        --output-dir "$STAGING_DIR" >/dev/null

    if [ "$matrix_volume_absent" = true ]; then
        snapshot_absent_volume matrix
    else
        snapshot_volume matrix "$matrix_volume" "$helper_image"
    fi
    snapshot_volume prometheus "$prometheus_volume" "$helper_image"
    snapshot_volume grafana "$grafana_volume" "$helper_image"
    snapshot_volume bisq2 "$bisq2_volume" "$helper_image"
    snapshot_volume alertmanager "$alertmanager_volume" "$helper_image"

    CAPTURE_COMPLETE=true
    resume_services

    log_info "Building value-free configuration inventory and manifest"
    python3 "$DR_HELPER" create-manifest \
        --root "$STAGING_DIR" \
        --env-file "$DOCKER_DIR/.env" \
        "${absent_volume_args[@]}" >/dev/null

    timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    encrypt_backup "$timestamp"
    apply_retention
    BACKUP_COMPLETED=true
    log_success "Encrypted backup completed: $COMPLETED_OUTPUT_NAME"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi

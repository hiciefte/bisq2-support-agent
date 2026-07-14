#!/bin/sh
set -eu

secret_file=${RUNTIME_SECRET_FILE:?RUNTIME_SECRET_FILE is required}
secret_label=${RUNTIME_SECRET_LABEL:-runtime secret}
secret_dir=$(dirname "$secret_file")

fail() {
    echo "Failed to initialize ${secret_label}: $1" >&2
    exit 1
}

validate_secret() {
    [ ! -L "$secret_file" ] || fail "symbolic links are not allowed"
    [ -f "$secret_file" ] || fail "secret path is not a regular file"
    [ -s "$secret_file" ] || fail "secret file is empty"

    secret_length=$(wc -c <"$secret_file" | tr -d '[:space:]')
    [ "$secret_length" = "64" ] || fail "secret file has an invalid length"

    secret_value=$(cat "$secret_file")
    case "$secret_value" in
        *[!0-9a-f]*) fail "secret file has an invalid format" ;;
    esac
}

[ -d "$secret_dir" ] || fail "secret volume is not mounted"

if [ -e "$secret_file" ] || [ -L "$secret_file" ]; then
    validate_secret
    echo "Preserving existing ${secret_label}"
    exit 0
fi

umask 077
temporary_file=$(mktemp "${secret_file}.tmp.XXXXXX") || fail "cannot create temporary file"
trap 'rm -f "$temporary_file"' EXIT HUP INT TERM

secret_value=$(od -An -N32 -tx1 /dev/urandom | tr -d '[:space:]')
[ "${#secret_value}" = "64" ] || fail "secure random generation failed"
printf '%s' "$secret_value" >"$temporary_file"

# The volume is mounted only into the two authorized consumers. World-readable
# mode inside that isolated volume lets Alertmanager's non-root user read its
# credential without granting the initializer extra ownership capabilities.
chmod 0444 "$temporary_file"
mv "$temporary_file" "$secret_file"
trap - EXIT HUP INT TERM

validate_secret
echo "Initialized ${secret_label}"

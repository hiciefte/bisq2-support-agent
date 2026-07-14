#!/bin/sh

# Load a fixed-format Compose runtime secret without evaluating its contents.
load_runtime_secret_from_file() {
    runtime_secret_name="$1"
    runtime_secret_file="$2"

    if [ -L "$runtime_secret_file" ] || [ ! -f "$runtime_secret_file" ]; then
        echo "Required runtime secret file is missing or invalid: ${runtime_secret_name}" >&2
        return 1
    fi

    runtime_secret_length=$(
        wc -c <"$runtime_secret_file" | tr -d '[:space:]'
    )
    if [ "$runtime_secret_length" != "64" ]; then
        echo "Required runtime secret has an invalid length: ${runtime_secret_name}" >&2
        return 1
    fi

    runtime_secret_value=$(cat "$runtime_secret_file")
    case "$runtime_secret_value" in
        *[!0-9a-f]*)
            echo "Required runtime secret has an invalid format: ${runtime_secret_name}" >&2
            return 1
            ;;
    esac

    export "${runtime_secret_name}=${runtime_secret_value}"
    unset runtime_secret_name runtime_secret_file
    unset runtime_secret_value runtime_secret_length
}

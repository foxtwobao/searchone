#!/bin/sh
# shellcheck shell=dash
set -u

# Check if it's a valid file
check_file() {
    local target="$1"

    if [ ! -f "$target" ]; then
        cat <<EOF
!!!
!!! ERROR
!!! "$target" is not a valid file, exiting...
!!!
EOF
        exit 127
    fi
}

# Check if it's a valid directory
check_directory() {
    local target="$1"

    if [ ! -d "$target" ]; then
        cat <<EOF
!!!
!!! ERROR
!!! "$target" is not a valid directory, exiting...
!!!
EOF
        exit 127
    fi
}

setup_ownership() {
    local target="$1"
    local type="$2"

    case "$type" in
        file | directory) ;;
        *)
            cat <<EOF
!!!
!!! ERROR
!!! "$type" is not a valid type, exiting...
!!!
EOF
            exit 1
            ;;
    esac

    target_ownership=$(stat -c %U:%G "$target")

    if [ "$target_ownership" != "searxng:searxng" ]; then
        if [ "${FORCE_OWNERSHIP:-true}" = true ] && [ "$(id -u)" -eq 0 ]; then
            chown -R searxng:searxng "$target"
        else
            cat <<EOF
!!!
!!! WARNING
!!! "$target" $type is not owned by "searxng:searxng"
!!! This may cause issues when running SearXNG
!!!
!!! Expected "searxng:searxng"
!!! Got "$target_ownership"
!!!
EOF
        fi
    fi
}

# Handle volume mounts
volume_handler() {
    local target="$1"

    check_directory "$target"
    setup_ownership "$target" "directory"
}

setup() {
    local template_settings="/usr/local/searxng/settings.template.yml"
    local target_settings="$__SEARXNG_CONFIG_PATH/settings.yml"

    if [ ! -f "$target_settings" ]; then
        cat <<EOF
...
... INFORMATION
... "$target_settings" does not exist, creating from template...
...
EOF
        cp -pfT "$template_settings" "$target_settings"

        sed -i "s/ultrasecretkey/$(head -c 24 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9')/g" "$target_settings"
    fi

    for engine in minimax zhipu; do
        /usr/local/searxng/.venv/bin/python -m searchone_control.settings_migration \
            --target "$target_settings" \
            --template "$template_settings" \
            --engine "$engine"
    done

    check_file "$target_settings"
}

setup_searchone() {
    searchone_data_path="${SEARCHONE_DATA_PATH:-/var/lib/searchone}"
    runtime_env_file="${SEARCHONE_RUNTIME_ENV_FILE:-$searchone_data_path/runtime-secrets.env}"

    mkdir -p "$searchone_data_path"
    setup_ownership "$searchone_data_path" "directory"

    /usr/local/searxng/.venv/bin/python -m searchone_control.bootstrap \
        --path "$runtime_env_file"

    set -a
    # shellcheck disable=SC1090
    . "$runtime_env_file"
    set +a

    export SEARCHONE_DATA_PATH="$searchone_data_path"
    export SEARCHONE_RUNTIME_ENV_FILE="$runtime_env_file"
    export SEARCHONE_DATABASE_PATH="${SEARCHONE_DATABASE_PATH:-$searchone_data_path/searchone.db}"
    export SEARXNG_SECRET="${SEARXNG_SECRET:-$SEARCHONE_SESSION_SECRET}"
}

cat <<EOF
SearchOne $__SEARXNG_VERSION
EOF

# Check for volume mounts
volume_handler "$__SEARXNG_CONFIG_PATH"
volume_handler "$__SEARXNG_DATA_PATH"

setup
setup_searchone

# root only features
if [ "$(id -u)" -eq 0 ]; then
    update-ca-certificates
fi

# ENVs aliases
export GRANIAN_PORT="${SEARXNG_PORT:-$GRANIAN_PORT}"

if [ "$(id -u)" -eq 0 ]; then
    exec gosu searxng /usr/local/searxng/.venv/bin/granian searchone_control.app:app
fi

exec /usr/local/searxng/.venv/bin/granian searchone_control.app:app

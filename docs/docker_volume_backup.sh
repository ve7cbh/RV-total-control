#!/bin/bash
#
# docker_volume_backup.sh
#
# Backs up EVERY mount (bind mounts AND Docker-managed named volumes) for
# each currently running container. `docker inspect` resolves the host
# path for both mount types via the .Source field, so this script doesn't
# need to treat them differently -- it just tars whatever .Source points to.
#
# Stops containers before archiving (for write consistency), archives,
# then restarts whatever was running. Prunes old archives.
#
# Run with sudo/root.

set -euo pipefail

# ---------------------------------------------------------------------------
# CONFIG — edit these for your setup
# ---------------------------------------------------------------------------
BACKUP_DIR="/home/ve7cbh/docker-volume-backups"   # BackInTime should point at this
LOG_FILE="/var/log/docker_volume_backup.log"
RETAIN_DAYS=7
LOCK_FILE="/run/docker_volume_backup.lock"

# Containers that must NEVER be stopped for backup, space separated.
NEVER_STOP=""

# Containers to skip entirely, space separated. Leave empty to back up all.
EXCLUDE_CONTAINERS=""

# Skip any mount whose SOURCE path contains one of these substrings
# (space separated). Useful for things like a shared host binary bind-
# mounted in read-only for convenience, which isn't really "data".
EXCLUDE_SOURCE_SUBSTRINGS="/usr/bin/"

# ---------------------------------------------------------------------------

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"
}

exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    log "Another backup run is already in progress. Exiting."
    exit 1
fi

log "=== Starting Docker backup ==="
mkdir -p "$BACKUP_DIR"

# --- 1. Snapshot mounts for every running container, BEFORE stopping anything
RUNNING_CONTAINERS=$(docker ps --format '{{.Names}}')

declare -A CONTAINER_MOUNTS   # container name -> "source\tdest" lines

for c in $RUNNING_CONTAINERS; do
    if echo " $EXCLUDE_CONTAINERS " | grep -q " $c "; then
        continue
    fi
    mounts=$(docker inspect -f '{{range .Mounts}}{{.Source}}{{"\t"}}{{.Destination}}{{"\n"}}{{end}}' "$c")
    if [ -n "$mounts" ]; then
        CONTAINER_MOUNTS["$c"]="$mounts"
    fi
done

# --- 2. Stop containers ------------------------------------------------------
STOPPED_THIS_RUN=""
for c in $RUNNING_CONTAINERS; do
    if echo " $EXCLUDE_CONTAINERS " | grep -q " $c "; then
        continue
    fi
    if echo " $NEVER_STOP " | grep -q " $c "; then
        log "Skipping stop for protected container: $c"
        continue
    fi
    log "Stopping container: $c"
    docker stop "$c" >/dev/null
    STOPPED_THIS_RUN="$STOPPED_THIS_RUN $c"
done

# --- 3. Archive each mount ----------------------------------------------------
FAILED=""
ARCHIVED_ANY=0

sanitize() {
    # turn a destination path like /var/lib/grafana into var_lib_grafana
    echo "$1" | sed 's#^/##; s#/#_#g'
}

for c in "${!CONTAINER_MOUNTS[@]}"; do
    found_for_container=0
    while IFS=$'\t' read -r src dest; do
        [ -z "$src" ] && continue

        skip=0
        for pat in $EXCLUDE_SOURCE_SUBSTRINGS; do
            case "$src" in
                *"$pat"*) skip=1 ;;
            esac
        done
        if [ "$skip" -eq 1 ]; then
            log "SKIP (excluded pattern): $c  $src"
            continue
        fi

        if [ ! -e "$src" ]; then
            log "SKIP: $c source '$src' does not exist"
            continue
        fi

        found_for_container=$((found_for_container + 1))
        name="${c}__$(sanitize "$dest")"
        ARCHIVE="$BACKUP_DIR/${name}.tar.gz"
        TMP_ARCHIVE="$ARCHIVE.tmp"

        log "Archiving $c: $src -> $dest"
        if [ -d "$src" ]; then
            ok=1
            tar czf "$TMP_ARCHIVE" -C "$src" . 2>>"$LOG_FILE" || ok=0
        else
            ok=1
            tar czf "$TMP_ARCHIVE" -C "$(dirname "$src")" "$(basename "$src")" 2>>"$LOG_FILE" || ok=0
        fi

        if [ "$ok" -eq 1 ]; then
            mv "$TMP_ARCHIVE" "$ARCHIVE"
            log "OK: $name -> $(du -h "$ARCHIVE" | cut -f1)"
            ARCHIVED_ANY=1
        else
            log "FAILED to archive: $name ($src)"
            FAILED="$FAILED $name"
            rm -f "$TMP_ARCHIVE"
        fi
    done <<< "${CONTAINER_MOUNTS[$c]}"

    if [ "$found_for_container" -eq 0 ]; then
        log "No mounts to back up for: $c (stateless container)"
    fi
done

# --- 4. Restart whatever we stopped -----------------------------------------
for c in $STOPPED_THIS_RUN; do
    log "Restarting container: $c"
    docker start "$c" >/dev/null
done

# --- 5. Prune old archives ---------------------------------------------------
log "Pruning archives older than $RETAIN_DAYS days"
find "$BACKUP_DIR" -name "*.tar.gz" -mtime "+$RETAIN_DAYS" -print -delete | tee -a "$LOG_FILE"

# --- 6. Summary ---------------------------------------------------------------
if [ -n "$FAILED" ]; then
    log "=== Completed WITH FAILURES:$FAILED ==="
    exit 1
else
    log "=== Completed successfully ==="
fi

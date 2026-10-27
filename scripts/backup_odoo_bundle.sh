#!/usr/bin/env bash
set -euo pipefail

# Create one consistent Odoo backup bundle containing PostgreSQL and filestore.
# The Odoo service is stopped briefly so no new attachments can be committed
# between the database dump and filestore snapshot.

DB_NAME=${DB_NAME:?Set DB_NAME to the Odoo database name}
COMPOSE_FILE_PATH=${COMPOSE_FILE_PATH:-docker-compose.yml}
DB_SERVICE=${DB_SERVICE:-db}
ODOO_SERVICE=${ODOO_SERVICE:-odoo}
BACKUP_ROOT=${BACKUP_ROOT:-backups}
FILESTORE_ROOT=${FILESTORE_ROOT:-/var/lib/odoo/.local/share/Odoo/filestore}
STAMP=${BACKUP_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
BUNDLE_NAME=${BUNDLE_NAME:-${DB_NAME}_${STAMP}}
OUTPUT_DIR=${BACKUP_ROOT%/}/${BUNDLE_NAME}

compose=(docker compose -f "$COMPOSE_FILE_PATH")
odoo_was_stopped=0

restart_odoo() {
    if [[ "$odoo_was_stopped" == 1 ]]; then
        "${compose[@]}" start "$ODOO_SERVICE" >/dev/null
    fi
}
trap restart_odoo EXIT INT TERM

if [[ -e "$OUTPUT_DIR" ]]; then
    echo "Backup destination already exists: $OUTPUT_DIR" >&2
    exit 1
fi

install -d -m 700 "$OUTPUT_DIR"

"${compose[@]}" ps --status running "$DB_SERVICE" | grep -q "$DB_SERVICE" || {
    echo "Database service is not running: $DB_SERVICE" >&2
    exit 1
}

"${compose[@]}" stop "$ODOO_SERVICE" >/dev/null
odoo_was_stopped=1

"${compose[@]}" exec -T "$DB_SERVICE" sh -eu -c \
    'pg_dump --format=custom --no-owner --no-acl --username="$POSTGRES_USER" --dbname="$1"' \
    sh "$DB_NAME" >"$OUTPUT_DIR/database.dump"

"${compose[@]}" run --rm --no-deps -T --entrypoint /bin/sh "$ODOO_SERVICE" \
    -eu -c 'test -d "$1/$2"; tar -C "$1" -czf - "$2"' \
    sh "$FILESTORE_ROOT" "$DB_NAME" >"$OUTPUT_DIR/filestore.tar.gz"

"${compose[@]}" exec -T "$DB_SERVICE" sh -eu -c \
    'pg_restore --list >/dev/null' <"$OUTPUT_DIR/database.dump"
tar -tzf "$OUTPUT_DIR/filestore.tar.gz" >/dev/null

git_commit=unknown
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git_commit=$(git rev-parse HEAD)
fi

cat >"$OUTPUT_DIR/manifest.txt" <<EOF
format=odoo-backup-bundle-v1
created_at_utc=$STAMP
database=$DB_NAME
git_commit=$git_commit
compose_file=$COMPOSE_FILE_PATH
database_service=$DB_SERVICE
odoo_service=$ODOO_SERVICE
filestore_root=$FILESTORE_ROOT
EOF

if command -v sha256sum >/dev/null 2>&1; then
    (cd "$OUTPUT_DIR" && sha256sum database.dump filestore.tar.gz manifest.txt >SHA256SUMS)
else
    (cd "$OUTPUT_DIR" && shasum -a 256 database.dump filestore.tar.gz manifest.txt >SHA256SUMS)
fi

chmod 600 "$OUTPUT_DIR"/*
restart_odoo
odoo_was_stopped=0
trap - EXIT INT TERM

echo "$OUTPUT_DIR"

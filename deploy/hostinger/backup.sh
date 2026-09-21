#!/usr/bin/env bash
# Sauvegarde PostgreSQL Docker + fichiers uploadés
# Usage : bash deploy/hostinger/backup.sh
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/paiement-fisc}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
OFFSITE_DIR="${BACKUP_OFFSITE_DIR:-}"
STAMP=$(date +%Y%m%d_%H%M%S)
DEST="$BACKUP_DIR/$STAMP"

mkdir -p "$DEST"
cd "$APP_DIR"

set -a
source .env
set +a

MANIFEST="$DEST/manifest.txt"
echo "backup_stamp=$STAMP" > "$MANIFEST"

docker compose exec -T db pg_dump \
    -U "${POSTGRES_USER:-paiement_fisc}" \
    "${POSTGRES_DB:-paiement_fisc}" -Fc > "$DEST/database.dump"

docker compose exec -T db pg_dump \
    -U "${POSTGRES_USER:-paiement_fisc}" \
    "${POSTGRES_DB:-paiement_fisc}" --schema-only > "$DEST/schema.sql"

docker compose exec -T app tar -czf - -C /app/static/uploads/poi . > "$DEST/uploads.tar.gz" 2>/dev/null || true
docker compose exec -T app tar -czf - -C /app/qr_codes . > "$DEST/qrcodes.tar.gz" 2>/dev/null || true

if command -v sha256sum >/dev/null 2>&1; then
    (cd "$DEST" && sha256sum *.dump *.tar.gz 2>/dev/null || true) > "$DEST/checksums.sha256"
fi

if [ -n "$OFFSITE_DIR" ]; then
    mkdir -p "$OFFSITE_DIR"
    rsync -a "$DEST/" "$OFFSITE_DIR/$STAMP/"
fi

find "$BACKUP_DIR" -maxdepth 1 -type d -mtime +"$RETENTION_DAYS" -exec rm -rf {} + 2>/dev/null || true

echo "Sauvegarde : $DEST"

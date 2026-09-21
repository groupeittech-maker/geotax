#!/usr/bin/env bash

# Sauvegarde PostgreSQL, fichiers uploadés et manifeste de vérification

# Usage : bash deploy/backup.sh

# Cron recommandé : 0 2 * * * /var/www/paiement-fisc/deploy/backup.sh

set -eu



APP_DIR="${APP_DIR:-/var/www/paiement-fisc}"

BACKUP_DIR="${BACKUP_DIR:-/var/backups/paiement-fisc}"

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

OFFSITE_DIR="${BACKUP_OFFSITE_DIR:-}"

STAMP=$(date +%Y%m%d_%H%M%S)

DEST="$BACKUP_DIR/$STAMP"



mkdir -p "$DEST"



if [ -f "$APP_DIR/.env" ]; then

    set -a

    # shellcheck disable=SC1091

    source "$APP_DIR/.env"

    set +a

fi



MANIFEST="$DEST/manifest.txt"

echo "backup_stamp=$STAMP" > "$MANIFEST"

echo "hostname=$(hostname)" >> "$MANIFEST"

echo "created_at=$(date -Iseconds 2>/dev/null || date)" >> "$MANIFEST"



if [ -n "${DATABASE_URL:-}" ] && [[ "$DATABASE_URL" == postgresql* ]]; then

    pg_dump "$DATABASE_URL" -Fc -f "$DEST/database.dump"

    pg_dump "$DATABASE_URL" --schema-only -f "$DEST/schema.sql"

    echo "Dump PostgreSQL : $DEST/database.dump"

    echo "database=database.dump" >> "$MANIFEST"

elif [ -f "$APP_DIR/instance/database.db" ]; then

    cp "$APP_DIR/instance/database.db" "$DEST/database.db"

    echo "Copie SQLite : $DEST/database.db"

    echo "database=database.db" >> "$MANIFEST"

fi



if [ -d "$APP_DIR/qr_codes" ]; then

    tar -czf "$DEST/qr_codes.tar.gz" -C "$APP_DIR" qr_codes

    echo "qr_codes=qr_codes.tar.gz" >> "$MANIFEST"

fi



if [ -d "$APP_DIR/static/uploads/poi" ]; then

    tar -czf "$DEST/poi_uploads.tar.gz" -C "$APP_DIR/static/uploads" poi

    echo "poi_uploads=poi_uploads.tar.gz" >> "$MANIFEST"

fi



# Checksums pour vérification d'intégrité

if command -v sha256sum >/dev/null 2>&1; then

    (cd "$DEST" && sha256sum *.dump *.tar.gz *.db 2>/dev/null || true) > "$DEST/checksums.sha256"

elif command -v shasum >/dev/null 2>&1; then

    (cd "$DEST" && shasum -a 256 *.dump *.tar.gz *.db 2>/dev/null || true) > "$DEST/checksums.sha256"

fi



# Copie off-site optionnelle (rsync vers un autre serveur ou disque)

if [ -n "$OFFSITE_DIR" ]; then

    mkdir -p "$OFFSITE_DIR"

    rsync -a "$DEST/" "$OFFSITE_DIR/$STAMP/"

    echo "offsite=$OFFSITE_DIR/$STAMP" >> "$MANIFEST"

fi



find "$BACKUP_DIR" -maxdepth 1 -type d -mtime +"$RETENTION_DAYS" -exec rm -rf {} + 2>/dev/null || true



echo "Sauvegarde créée : $DEST"

echo "Manifeste : $MANIFEST"


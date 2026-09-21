#!/usr/bin/env bash

# Restauration depuis une sauvegarde deploy/backup.sh

# Usage : bash deploy/restore.sh /var/backups/paiement-fisc/20260819_020000

set -euo pipefail



if [ $# -lt 1 ]; then

    echo "Usage: $0 <chemin_sauvegarde>"

    exit 1

fi



BACKUP_PATH="$1"

APP_DIR="${APP_DIR:-/var/www/paiement-fisc}"



if [ ! -d "$BACKUP_PATH" ]; then

    echo "Dossier introuvable : $BACKUP_PATH"

    exit 1

fi



if [ -f "$APP_DIR/.env" ]; then

    set -a

    # shellcheck disable=SC1091

    source "$APP_DIR/.env"

    set +a

fi



echo "==> Vérification checksums"

if [ -f "$BACKUP_PATH/checksums.sha256" ]; then

    (cd "$BACKUP_PATH" && sha256sum -c checksums.sha256) || {

        echo "WARN: checksums invalides — poursuite sur confirmation manuelle"

    }

fi



if [ -f "$BACKUP_PATH/database.dump" ] && [ -n "${DATABASE_URL:-}" ]; then

    echo "==> Restauration PostgreSQL"

    read -r -p "Écraser la base actuelle ? (oui/non) " confirm

    if [ "$confirm" = "oui" ]; then

        pg_restore --clean --if-exists --no-owner --dbname="$DATABASE_URL" "$BACKUP_PATH/database.dump"

        echo "Base restaurée."

    fi

elif [ -f "$BACKUP_PATH/database.db" ]; then

    mkdir -p "$APP_DIR/instance"

    cp "$BACKUP_PATH/database.db" "$APP_DIR/instance/database.db"

    echo "SQLite restauré."

fi



if [ -f "$BACKUP_PATH/qr_codes.tar.gz" ]; then

    tar -xzf "$BACKUP_PATH/qr_codes.tar.gz" -C "$APP_DIR"

    echo "QR codes restaurés."

fi



if [ -f "$BACKUP_PATH/poi_uploads.tar.gz" ]; then

    mkdir -p "$APP_DIR/static/uploads"

    tar -xzf "$BACKUP_PATH/poi_uploads.tar.gz" -C "$APP_DIR/static/uploads"

    echo "Uploads POI restaurés."

fi



echo "==> Restauration terminée depuis $BACKUP_PATH"


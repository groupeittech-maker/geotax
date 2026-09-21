#!/usr/bin/env bash
# LEGACY — Migration unique SQLite → PostgreSQL Docker
# À utiliser UNIQUEMENT si vos données n'ont jamais été migrées vers PostgreSQL.
# Si vos données sont déjà sur PostgreSQL : utilisez pg_dump / pg_restore (voir DEPLOY_HOSTINGER.md).
#
# Usage : bash deploy/hostinger/migrate-sqlite.sh chemin/vers/database.db
set -euo pipefail

SQLITE_PATH="${1:-}"
APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$APP_DIR"

if [ -z "$SQLITE_PATH" ] || [ ! -f "$SQLITE_PATH" ]; then
    echo "Usage : bash deploy/hostinger/migrate-sqlite.sh instance/database.db"
    exit 1
fi

BASENAME=$(basename "$SQLITE_PATH")
docker cp "$SQLITE_PATH" "paiement-fisc-app:/tmp/$BASENAME"

docker compose exec -T app python deploy/migrate_sqlite_to_postgres.py \
    --sqlite "/tmp/$BASENAME" \
    --skip-empty-check

echo "Migration terminée. Redémarrez si nécessaire : docker compose restart app"

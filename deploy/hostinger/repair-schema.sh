#!/usr/bin/env bash
# Répare le schéma PostgreSQL (colonnes manquantes → Internal Server Error).
# Usage : cd /opt/paiement-fisc && bash deploy/hostinger/repair-schema.sh
set -eu

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$APP_DIR"

echo "=== Réparation schéma base de données ==="

echo ">> Alembic upgrade"
docker compose --env-file .env exec -T app flask db upgrade || echo "WARN alembic"

echo ">> Colonnes pays (centre carte)"
docker compose --env-file .env exec -T db psql -U "${POSTGRES_USER:-paiement_fisc}" -d "${POSTGRES_DB:-paiement_fisc}" <<'SQL'
ALTER TABLE pays ADD COLUMN IF NOT EXISTS center_lat DOUBLE PRECISION;
ALTER TABLE pays ADD COLUMN IF NOT EXISTS center_lng DOUBLE PRECISION;
ALTER TABLE pays ADD COLUMN IF NOT EXISTS default_zoom INTEGER DEFAULT 6;
SQL

echo ">> Migrations Python légères"
docker compose --env-file .env exec -T app python -c "
from app import app, _run_schema_migrations
with app.app_context():
    _run_schema_migrations()
    print('Schema migrations OK')
" || echo "WARN migrations Python"

echo ">> Migrations pays multi-pays (CG / RCA distincts)"
docker compose --env-file .env exec -T app python -c "
from app import app, _migrate_pays_map_metadata
with app.app_context():
    _migrate_pays_map_metadata()
    print('Pays multi-pays OK')
" || echo "WARN migrations pays"

echo ">> Test pages"
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/login || echo 000)
echo "GET /login -> HTTP $HTTP_CODE"

if [ "$HTTP_CODE" != "200" ]; then
    echo "Logs app :"
    docker compose --env-file .env logs app --tail=30
fi

echo "=== Terminé ==="

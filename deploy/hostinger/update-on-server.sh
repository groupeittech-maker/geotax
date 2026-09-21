#!/usr/bin/env bash
# Mise à jour rapide sur le VPS (sans réimport des données)
# Usage sur le VPS : bash deploy/hostinger/update-on-server.sh
# Ou depuis Windows : .\deploy\hostinger\deploy-to-vps.ps1 -SkipDump -SkipRestore
set -eu

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$APP_DIR"

echo "==> Mise à jour GeoTax dans $APP_DIR"

if [ ! -f .env ]; then
    echo "Erreur : .env manquant"
    exit 1
fi

grep -q '^HTTP_PORT=' .env || echo 'HTTP_PORT=8080' >> .env
grep -q '^LOG_FORMAT=' .env || echo 'LOG_FORMAT=json' >> .env

echo "==> Pull images PostGIS + Redis"
docker compose --env-file .env pull db redis nginx 2>/dev/null || true

echo "==> Rebuild app + worker"
docker compose --env-file .env build --pull app worker
docker compose --env-file .env up -d

echo "==> Attente PostgreSQL..."
for i in $(seq 1 30); do
    if docker compose --env-file .env exec -T db pg_isready -U "${POSTGRES_USER:-paiement_fisc}" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

echo "==> Migrations Alembic"
docker compose --env-file .env exec -T app flask db upgrade || echo "WARN: migrations"

echo "==> PostGIS (si image postgis/postgis)"
docker compose --env-file .env exec -T app python -c "
from app import app
from models import db
from spatial_utils import ensure_postgis, ensure_geom_column, backfill_all_geoms
with app.app_context():
    try:
        ensure_postgis(db.engine)
        ensure_geom_column(db.engine, db.session)
        n = backfill_all_geoms(db.session)
        print(f'geom synchronisé: {n} POI')
    except Exception as e:
        print(f'PostGIS: {e}')
" || true

HTTP_PORT=$(grep '^HTTP_PORT=' .env | cut -d= -f2 || echo 8080)
echo ""
docker compose --env-file .env ps
echo ""
echo "Santé : curl -s http://127.0.0.1:${HTTP_PORT}/health/ready"
curl -sS --max-time 10 "http://127.0.0.1:${HTTP_PORT}/health/ready" || true
echo ""

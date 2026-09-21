#!/usr/bin/env bash
# Init DB complète (seeds, migrations POI) — à lancer manuellement ou après déploiement.
# Usage : bash deploy/hostinger/run-init-db.sh
set -eu

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$APP_DIR"

echo "==> init_db complet (peut prendre plusieurs minutes)..."
docker compose --env-file .env exec -T app python -c "from app import init_db; init_db()"
echo "==> Terminé"

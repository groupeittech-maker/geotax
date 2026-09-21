#!/usr/bin/env bash
# Exécuté sur le VPS après extraction de app.tar.gz
# Usage : bash deploy/hostinger/remote-update.sh [--skip-restore]
set -eu

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$APP_DIR"

SKIP_RESTORE=0
if [ "${1:-}" = "--skip-restore" ]; then
    SKIP_RESTORE=1
fi

echo "==> Répertoire : $APP_DIR"

if [ ! -f .env ]; then
    cp .env.docker.example .env
    SECRET=$(openssl rand -hex 32)
    PASS=$(openssl rand -hex 16)
    sed -i "s/changez-cette-cle-secrete-longue/$SECRET/" .env
    sed -i "s/changez-ce-mot-de-passe-fort/$PASS/" .env
    chmod 600 .env
    echo "Fichier .env créé."
fi

grep -q '^HTTP_PORT=' .env && sed -i 's/^HTTP_PORT=.*/HTTP_PORT=8080/' .env || echo 'HTTP_PORT=8080' >> .env
grep -q '^SESSION_COOKIE_SECURE=' .env && sed -i 's/^SESSION_COOKIE_SECURE=.*/SESSION_COOKIE_SECURE=false/' .env || echo 'SESSION_COOKIE_SECURE=false' >> .env
grep -q '^LOG_FORMAT=' .env || echo 'LOG_FORMAT=json' >> .env

bash deploy/hostinger/install-docker.sh
bash deploy/hostinger/deploy.sh

if [ "$SKIP_RESTORE" -eq 0 ] && [ -f deploy/hostinger/backup.dump ]; then
    echo "==> Restauration PostgreSQL depuis backup.dump"
    cat deploy/hostinger/backup.dump | docker compose --env-file .env exec -T db \
        pg_restore -U paiement_fisc -d paiement_fisc --clean --if-exists --no-owner --no-acl 2>/dev/null || true
    docker compose --env-file .env exec -T app python deploy/verify_migration_status.py || true
    echo "==> Redémarrage app après restauration base"
    docker compose --env-file .env up -d --force-recreate app worker
    bash deploy/hostinger/wait-app-ready.sh 90 2 || true
else
    echo "==> Mise à jour code uniquement (pas de restauration base)"
fi

docker compose --env-file .env restart nginx

echo "==> Terminé"
docker compose --env-file .env ps

HTTP_PORT=$(grep '^HTTP_PORT=' .env | cut -d= -f2 || echo 8080)
echo ""
echo "Santé :"
curl -sS --max-time 10 "http://127.0.0.1:${HTTP_PORT}/health/ready" || true
echo ""

#!/usr/bin/env bash
# Réparation rapide 502 Bad Gateway — à exécuter SUR LE VPS
# Usage : cd /opt/paiement-fisc && bash deploy/hostinger/fix-502.sh
set -eu

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$APP_DIR"

echo "=== GeoTax — réparation 502 ==="
echo "Répertoire : $APP_DIR"

grep -q '^HTTP_PORT=' .env 2>/dev/null || echo 'HTTP_PORT=8080' >> .env
HTTP_PORT=$(grep '^HTTP_PORT=' .env | cut -d= -f2 || echo 8080)

echo ""
echo "=== 1. État conteneurs ==="
docker compose --env-file .env ps

echo ""
echo "=== 2. Redémarrage db + redis ==="
docker compose --env-file .env up -d db redis
sleep 5

echo ""
echo "=== 3. Entrypoint minimal + rebuild app ==="
grep -q '^RUN_INIT_DB=' .env 2>/dev/null && sed -i 's/^RUN_INIT_DB=.*/RUN_INIT_DB=0/' .env || echo 'RUN_INIT_DB=0' >> .env
grep -q '^SKIP_GEOM_BACKFILL=' .env 2>/dev/null && sed -i 's/^SKIP_GEOM_BACKFILL=.*/SKIP_GEOM_BACKFILL=1/' .env || echo 'SKIP_GEOM_BACKFILL=1' >> .env

docker compose --env-file .env build --no-cache app worker
docker compose --env-file .env up -d --force-recreate app worker

echo ""
echo "=== 4. Attente app (max 3 min) ==="
bash deploy/hostinger/wait-app-ready.sh 90 2 || true

echo ""
echo "=== 5. Redémarrage nginx Docker ==="
docker compose --env-file .env up -d nginx
docker compose --env-file .env restart nginx

echo ""
echo "=== 6. Test local ==="
curl -sS --max-time 10 "http://127.0.0.1:${HTTP_PORT}/health/ready" && echo "" || echo "ECHEC :8080/health/ready"

echo ""
echo "=== 7. Logs app (dernières lignes) ==="
docker compose --env-file .env logs app --tail=40

echo ""
echo "=== 8. Nginx hôte (HTTPS) ==="
if command -v systemctl >/dev/null 2>&1; then
    systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null || true
fi
curl -sS --max-time 10 -k "https://127.0.0.1/health/ready" -H "Host: geotax.ittechmed.com" 2>/dev/null || \
    curl -sS --max-time 10 "http://127.0.0.1:${HTTP_PORT}/health/ready" || true
echo ""

echo "=== Fin — testez https://geotax.ittechmed.com ==="

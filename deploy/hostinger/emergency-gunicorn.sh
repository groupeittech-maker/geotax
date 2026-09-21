#!/usr/bin/env bash
# Démarrage d'urgence si l'entrypoint bloque encore (502).
# Usage : cd /opt/paiement-fisc && bash deploy/hostinger/emergency-gunicorn.sh
set -eu

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$APP_DIR"

echo "=== URGENCE GeoTax : Gunicorn direct (sans entrypoint) ==="

docker compose --env-file .env up -d db redis
sleep 3

docker compose --env-file .env \
  -f docker-compose.yml \
  -f docker-compose.emergency.yml \
  up -d --force-recreate app worker nginx

sleep 8
HTTP_PORT=$(grep '^HTTP_PORT=' .env | cut -d= -f2 || echo 8080)

echo "Test local :"
curl -sS --max-time 10 "http://127.0.0.1:${HTTP_PORT}/health/ready" && echo "" || echo "ECHEC health"

echo "Logs app :"
docker compose --env-file .env logs app --tail=25

if command -v systemctl >/dev/null 2>&1; then
    systemctl reload nginx 2>/dev/null || true
fi

echo ""
echo "Si OK : https://geotax.ittechmed.com"
echo "Puis redéployez le code corrigé et relancez fix-502.sh"

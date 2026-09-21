#!/usr/bin/env bash
# Attend que l'application réponde (via nginx, sans docker exec bloquant).
set -eu

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$APP_DIR"

MAX_ATTEMPTS="${1:-90}"
SLEEP_SEC="${2:-2}"

HTTP_PORT=$(grep '^HTTP_PORT=' .env 2>/dev/null | cut -d= -f2 || echo 8080)
HEALTH_URL="http://127.0.0.1:${HTTP_PORT}/health/ready"

echo "==> Attente démarrage app (${MAX_ATTEMPTS} x ${SLEEP_SEC}s max)..."
echo "    Sonde : ${HEALTH_URL}"

for i in $(seq 1 "$MAX_ATTEMPTS"); do
    if curl -sf --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
        echo "App prête (après ${i}x${SLEEP_SEC}s)."
        exit 0
    fi

    if [ $((i % 5)) -eq 0 ]; then
        echo "  ... en cours (${i}/${MAX_ATTEMPTS}) — migrations / init_db en cours ?"
        docker compose --env-file .env logs app --tail=8 2>/dev/null || true
    fi
    sleep "$SLEEP_SEC"
done

echo "WARN: app non prête après $((MAX_ATTEMPTS * SLEEP_SEC))s."
echo "      Vérifiez : docker compose --env-file .env logs app --tail=80"
exit 1

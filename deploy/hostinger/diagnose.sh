#!/usr/bin/env bash
# Diagnostic rapide 502 / santé — bash deploy/hostinger/diagnose.sh
set -eu
cd "$(dirname "$0")/../.."

echo "=== Conteneurs ==="
docker compose --env-file .env ps

echo ""
echo "=== Logs app (30 dernières lignes) ==="
docker compose --env-file .env logs app --tail 30

echo ""
echo "=== Test Gunicorn direct (dans conteneur app) ==="
docker compose --env-file .env exec -T app python -c "
import urllib.request
try:
    r = urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)
    print('OK app:8000/health ->', r.read().decode()[:200])
except Exception as e:
    print('ECHEC app:8000 ->', e)
" || true

echo ""
echo "=== Test via nginx :8080 ==="
curl -sS --max-time 5 http://127.0.0.1:8080/health/ready || echo "ECHEC nginx:8080"

echo ""
echo "=== Processus dans app ==="
docker compose --env-file .env exec -T app ps aux 2>/dev/null || true

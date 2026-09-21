#!/usr/bin/env bash
# Déploiement / mise à jour sur VPS Hostinger (PostGIS + Redis + Worker)
# Usage depuis /opt/paiement-fisc :
#   sudo bash deploy/hostinger/deploy.sh
set -eu

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$APP_DIR"

echo "==> Répertoire : $APP_DIR"

if [ ! -f .env ]; then
    if [ -f .env.docker.example ]; then
        cp .env.docker.example .env
        SECRET=$(openssl rand -hex 32)
        PASS=$(openssl rand -hex 16)
        sed -i "s/changez-cette-cle-secrete-longue/$SECRET/" .env
        sed -i "s/changez-ce-mot-de-passe-fort/$PASS/" .env
        chmod 600 .env
        echo "Fichier .env créé (SECRET_KEY et POSTGRES_PASSWORD générés)."
    else
        echo "Erreur : .env manquant. Copiez .env.docker.example vers .env"
        exit 1
    fi
fi

# Port 8080 si nginx hôte occupe déjà le port 80 (Mobility Health, etc.)
if ! grep -q '^HTTP_PORT=' .env 2>/dev/null; then
    echo 'HTTP_PORT=8080' >> .env
fi

echo "==> Pull images (PostGIS, Redis, Nginx)"
docker compose --env-file .env pull db redis nginx 2>/dev/null || true

echo "==> Build et démarrage des conteneurs (app + worker + db + redis + nginx)"
docker compose --env-file .env build --pull app worker
docker compose --env-file .env up -d

bash deploy/hostinger/wait-app-ready.sh 90 2 || true

echo "==> État des services"
docker compose --env-file .env ps

HTTP_PORT=$(grep '^HTTP_PORT=' .env | cut -d= -f2 || echo 8080)
echo ""
echo "Déploiement terminé."
echo "  Application : http://$(curl -s ifconfig.me 2>/dev/null || echo 'VOTRE-IP'):${HTTP_PORT}"
echo "  Santé       : curl http://127.0.0.1:${HTTP_PORT}/health/ready"
echo "  Logs        : docker compose --env-file .env logs -f app"
echo "  Admin       : admin / admin123 (changez le mot de passe après connexion)"

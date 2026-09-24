#!/usr/bin/env bash
# Injecte la configuration SMTP dans .env à partir des variables d'environnement
# (alimentées par les secrets GitHub au déploiement — aucun secret dans le repo).
# Sans SMTP_HOST défini, l'étape est ignorée.
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$APP_DIR"

if [ ! -f .env ]; then
    echo "Erreur : .env manquant"
    exit 1
fi

if [ -z "${SMTP_HOST:-}" ]; then
    echo "SMTP non configuré (SMTP_HOST absent) — étape ignorée"
    exit 0
fi

set_kv() {
    local key="$1" val="${2:-}"
    [ -z "$val" ] && return 0
    if grep -q "^${key}=" .env; then
        sed -i "s|^${key}=.*|${key}=${val}|" .env
    else
        echo "${key}=${val}" >> .env
    fi
}

set_kv SMTP_HOST  "$SMTP_HOST"
set_kv SMTP_PORT  "${SMTP_PORT:-587}"
set_kv SMTP_USER  "${SMTP_USER:-}"
set_kv SMTP_PASS  "${SMTP_PASS:-}"
set_kv MAIL_FROM  "${MAIL_FROM:-conctact@ittechmed.com}"
set_kv MAIL_TO    "${MAIL_TO:-conctact@ittechmed.com}"

echo "==> SMTP configuré : ${SMTP_USER}@${SMTP_HOST}:${SMTP_PORT} → ${MAIL_TO:-conctact@ittechmed.com}"

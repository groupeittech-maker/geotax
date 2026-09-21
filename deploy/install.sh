#!/usr/bin/env bash

# Script d'installation sur VPS Ubuntu/Debian

# Usage : sudo bash deploy/install.sh

set -euo pipefail



APP_DIR="${APP_DIR:-/var/www/paiement-fisc}"

APP_USER="${APP_USER:-www-data}"



echo "==> Mise à jour des paquets système"

apt-get update

apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx postgresql-client



echo "==> PostgreSQL"

bash "$APP_DIR/deploy/setup_postgres.sh" | tee /tmp/paiement-fisc-db-url.txt



echo "==> Préparation du répertoire $APP_DIR"

mkdir -p "$APP_DIR"

chown -R "$APP_USER:$APP_USER" "$APP_DIR"



if [ ! -d "$APP_DIR/venv" ]; then

    echo "==> Création de l'environnement virtuel Python"

    sudo -u "$APP_USER" python3 -m venv "$APP_DIR/venv"

fi



echo "==> Installation des dépendances Python"

sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip

sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"



if [ ! -f "$APP_DIR/.env" ]; then

    echo "==> Création du fichier .env"

    cp "$APP_DIR/.env.example" "$APP_DIR/.env"

    SECRET=$(openssl rand -hex 32)

    sed -i "s/changez-cette-cle-secrete/$SECRET/" "$APP_DIR/.env"

    DB_URL=$(grep '^DATABASE_URL=' /tmp/paiement-fisc-db-url.txt | tail -1 || true)

    if [ -n "$DB_URL" ]; then

        sed -i "s|^DATABASE_URL=.*|$DB_URL|" "$APP_DIR/.env"

    fi

    chown "$APP_USER:$APP_USER" "$APP_DIR/.env"

    chmod 600 "$APP_DIR/.env"

    echo "    SECRET_KEY et DATABASE_URL configurés dans .env"

fi



mkdir -p "$APP_DIR/qr_codes" "$APP_DIR/static/uploads/poi"

chown -R "$APP_USER:$APP_USER" "$APP_DIR/qr_codes" "$APP_DIR/static/uploads"



echo "==> Initialisation du schéma PostgreSQL"

sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && set -a && source .env && set +a && venv/bin/python -c 'from app import init_db; init_db()'"



echo "==> Service systemd"

cp "$APP_DIR/deploy/paiement-fisc.service" /etc/systemd/system/paiement-fisc.service

sed -i "s|/var/www/paiement-fisc|$APP_DIR|g" /etc/systemd/system/paiement-fisc.service

systemctl daemon-reload

systemctl enable paiement-fisc



echo "==> Nginx"

if [ ! -f /etc/nginx/sites-available/paiement-fisc ]; then

    cp "$APP_DIR/deploy/nginx.conf.example" /etc/nginx/sites-available/paiement-fisc

    ln -sf /etc/nginx/sites-available/paiement-fisc /etc/nginx/sites-enabled/paiement-fisc

    sed -i "s|/var/www/paiement-fisc|$APP_DIR|g" /etc/nginx/sites-available/paiement-fisc

fi



echo ""

echo "Installation terminée."

echo "1. Éditez $APP_DIR/.env (GOOGLE_MAPS_API_KEY, domaine, etc.)"

echo "2. Éditez /etc/nginx/sites-available/paiement-fisc (server_name)"

echo "3. sudo nginx -t && sudo systemctl reload nginx"

echo "4. sudo systemctl start paiement-fisc"

echo "5. sudo certbot --nginx -d votre-domaine.fr  (HTTPS)"

echo ""
echo "Import PostgreSQL (données existantes) :"
echo "  pg_dump ... -Fc -f backup.dump && pg_restore -d \$DATABASE_URL --clean --if-exists backup.dump"
echo ""
echo "Legacy SQLite (une seule fois, si jamais migré) :"
echo "  python deploy/migrate_sqlite_to_postgres.py --sqlite instance/database.db"
echo "  python deploy/verify_migration_status.py"

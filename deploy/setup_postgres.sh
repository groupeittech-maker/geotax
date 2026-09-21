#!/usr/bin/env bash
# Crée la base PostgreSQL et affiche la DATABASE_URL
# Usage : sudo bash deploy/setup_postgres.sh
set -euo pipefail

DB_NAME="${POSTGRES_DB:-paiement_fisc}"
DB_USER="${POSTGRES_USER:-paiement_fisc}"
DB_PASS="${POSTGRES_PASSWORD:-}"

if [ -z "$DB_PASS" ]; then
    DB_PASS=$(openssl rand -hex 16)
fi

if ! command -v psql >/dev/null 2>&1; then
    echo "Installation de PostgreSQL..."
    apt-get update
    apt-get install -y postgresql postgresql-contrib
    systemctl enable postgresql
    systemctl start postgresql
fi

sudo -u postgres psql -v ON_ERROR_STOP=1 <<EOF
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER') THEN
    CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';
  ELSE
    ALTER USER $DB_USER WITH PASSWORD '$DB_PASS';
  END IF;
END
\$\$;

SELECT 'CREATE DATABASE $DB_NAME OWNER $DB_USER'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')\gexec

GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
EOF

echo ""
echo "PostgreSQL prêt."
echo "DATABASE_URL=postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}"
echo ""
echo "Ajoutez cette ligne dans /var/www/paiement-fisc/.env"

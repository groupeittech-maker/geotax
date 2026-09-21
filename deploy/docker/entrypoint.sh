#!/bin/sh
# Entrypoint minimal — Gunicorn doit démarrer en quelques secondes (pas de init_db ici).
set -e

if [ "${1:-}" = "rq" ] || [ "${RUN_MODE:-}" = "worker" ]; then
    echo "==> Démarrage worker RQ"
    exec "$@"
fi

echo "==> Attente PostgreSQL..."
python <<'PY'
import os, sys, time
from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL", "")
if not url:
    sys.exit("DATABASE_URL manquant")

for attempt in range(1, 31):
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("PostgreSQL disponible.")
        break
    except Exception as exc:
        print(f"Tentative {attempt}/30 : {exc}")
        time.sleep(2)
else:
    sys.exit("Impossible de joindre PostgreSQL")
PY

if [ "${SKIP_DB_UPGRADE:-0}" != "1" ]; then
    echo "==> Migrations Alembic"
    export FLASK_APP=app:app
    flask db upgrade || echo "WARN: flask db upgrade — voir logs"
fi

echo "==> Démarrage Gunicorn"
exec gunicorn -c deploy/gunicorn.conf.py app:app

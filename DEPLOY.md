# Guide de déploiement — Paiement Fiscal

**Base de données : PostgreSQL uniquement** (production, Docker, VPS).

SQLite n'est plus utilisé. L'ancien fichier `instance/database.db` peut exister
localement ; s'il contient encore des données, migrez-le **une seule fois** avec :

```bash
python deploy/migrate_sqlite_to_postgres.py --sqlite instance/database.db
python deploy/verify_migration_status.py
```

---

## Choisir votre mode de déploiement

| Mode | Guide | Quand l'utiliser |
|------|-------|------------------|
| **Docker sur VPS Hostinger** | [DEPLOY_HOSTINGER.md](DEPLOY_HOSTINGER.md) | **Recommandé** — production Hostinger |
| **Sans Docker (systemd)** | [DEPLOY.md](DEPLOY.md) | VPS sans Docker, admin système |

---

## Avant chaque déploiement

1. **`DATABASE_URL`** doit pointer vers PostgreSQL dans `.env`
2. Vérifier la migration :
   ```bash
   python deploy/verify_migration_status.py
   ```
3. Vérifier l'application :
   ```bash
   python deploy/verify_postgres.py
   ```

---

## Transférer des données PostgreSQL existantes

Si vos données sont **déjà dans PostgreSQL** (local ou autre serveur) :

```bash
# Export
pg_dump "$DATABASE_URL" -Fc -f backup.dump

# Import (Docker Hostinger, après docker compose up)
docker compose --env-file .env exec -T db pg_restore \
  -U paiement_fisc -d paiement_fisc --clean --if-exists < backup.dump
```

**Ne pas** utiliser le script SQLite si vos données sont déjà sur PostgreSQL.

---

## Fichiers legacy (SQLite)

Conservés pour rétrocompatibilité uniquement :

| Fichier | Usage |
|---------|-------|
| `deploy/migrate_sqlite_to_postgres.py` | Migration unique SQLite → PostgreSQL |
| `deploy/hostinger/migrate-sqlite.sh` | Idem, via Docker (legacy) |

Après migration réussie et vérification, vous pouvez archiver `instance/database.db`.

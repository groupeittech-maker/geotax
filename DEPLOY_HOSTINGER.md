# Déploiement Docker sur VPS Hostinger

Application **100 % PostgreSQL**. Aucune base SQLite en production.

## Prérequis

- VPS Hostinger (Ubuntu/Debian), accès SSH
- Domaine → IP du VPS (pour HTTPS)
- Ports 80 et 443 ouverts (hPanel → Firewall)

## Architecture

```
Internet :443  →  nginx hôte (geotax.ittechmed.com)
                        ↓ :8080
              Docker nginx → app (Gunicorn) → db (PostgreSQL + PostGIS)
                                         ↘ redis ← worker (RQ)
              Volumes : pgdata, redis_data, uploads_data, qrcodes_data
```

**Note** : le port **80/443** du VPS héberge déjà une autre app (Mobility Health).
GeoTax écoute sur **8080** en interne ; nginx hôte fait le proxy HTTPS.

---

## Déploiement depuis Windows (recommandé)

### Prérequis

1. **SSH** : mot de passe root Hostinger (hPanel → VPS → SSH access → réinitialiser si besoin)
2. **PostgreSQL local** : pour exporter vos données (`pg_dump`)
3. **tar** : inclus dans Windows 10+

### Commande unique

```powershell
cd "D:\Nos logiciels\Paiement fisc"
.\deploy\hostinger\deploy-to-vps.ps1 -VpsHost root@76.13.36.246
```

Le script :
1. Exporte votre base PostgreSQL locale → `deploy/hostinger/backup.dump`
2. Compresse le projet (sans `.env`, sans `instance/`)
3. Transfère via SCP sur `/opt/paiement-fisc`
4. Installe Docker, lance PostGIS + Redis + Worker
5. Applique les migrations Alembic (PostGIS, index spatial)
6. Restaure vos données

**Options** :
- `-SkipDump` : ne pas ré-exporter la base (utilise le dump existant)
- `-SkipRestore` : déployer sans importer les données (installation vierge)

### Alternative automatisée (mot de passe en variable session)

```powershell
pip install -r deploy/requirements-deploy.txt

# Export manuel si besoin
$env:PGPASSWORD = '...'
& "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" $env:DATABASE_URL -Fc -f deploy\hostinger\backup.dump

$env:DEPLOY_SSH_PASS = 'VOTRE_MOT_DE_PASSE_ROOT'   # ne jamais committer
$env:DEPLOY_DUMP_LOCAL = "$PWD\deploy\hostinger\backup.dump"
python deploy/hostinger/remote_deploy.py
```

### HTTPS sur geotax.ittechmed.com

Une fois l'app accessible sur `:8080` :

```powershell
$env:DEPLOY_SSH_PASS = '...'
python deploy/hostinger/setup_geotax_ssl.py
```

Puis dans `.env` sur le VPS : `SESSION_COOKIE_SECURE=true`

---

## Déploiement initial (sans données existantes)

```bash
ssh root@VOTRE_IP_HOSTINGER

mkdir -p /opt/paiement-fisc
# git clone ou scp du projet
cd /opt/paiement-fisc

sudo bash deploy/hostinger/install-docker.sh
cp .env.docker.example .env
nano .env   # POSTGRES_PASSWORD, SECRET_KEY

sudo bash deploy/hostinger/deploy.sh
```

→ http://VOTRE_IP — connexion **admin / admin123** (changez le mot de passe).

`init_db()` crée automatiquement les tables et données par défaut dans PostgreSQL Docker.

---

## Déploiement avec données PostgreSQL existantes

**Cas le plus fréquent** si vous avez déjà migré vers PostgreSQL en local.

### 1. Exporter depuis votre PostgreSQL actuel

Sur la machine où sont vos données :

```bash
# Windows (PowerShell) — adapter user/mot de passe
$env:PGPASSWORD='votre_mot_de_passe'
& "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" -U paiement_fisc -h localhost -d paiement_fisc -Fc -f backup.dump
```

Ou avec `DATABASE_URL` :

```bash
pg_dump "$DATABASE_URL" -Fc -f backup.dump
```

### 2. Déployer Docker sur Hostinger

```bash
sudo bash deploy/hostinger/deploy.sh
```

### 3. Importer dans PostgreSQL Docker

```bash
scp backup.dump root@VOTRE_IP:/tmp/
cd /opt/paiement-fisc
docker compose --env-file .env exec -T db pg_restore \
  -U paiement_fisc -d paiement_fisc --clean --if-exists < /tmp/backup.dump
docker compose --env-file .env restart app
```

### 4. Vérifier

```bash
docker compose --env-file .env exec app python deploy/verify_migration_status.py
docker compose --env-file .env exec app python deploy/verify_postgres.py
```

---

## Migration SQLite (legacy — une seule fois)

**Uniquement si** vous n'avez **jamais** migré et que vos données sont encore
dans `instance/database.db` :

```bash
bash deploy/hostinger/migrate-sqlite.sh /chemin/vers/database.db
```

Si vous avez déjà PostgreSQL avec vos données → utilisez **pg_dump / pg_restore** (section ci-dessus).

---

## HTTPS (Let's Encrypt)

```bash
docker compose --env-file .env stop nginx
apt-get install -y certbot
certbot certonly --standalone -d votre-domaine.fr --agree-tos -m votre@email.fr

cp deploy/docker/nginx-ssl.conf.example deploy/docker/nginx.conf
sed -i 's/votre-domaine.fr/VOTRE-DOMAINE.fr/g' deploy/docker/nginx.conf

docker compose --env-file .env -f docker-compose.yml -f docker-compose.ssl.yml up -d nginx
```

Renouvellement :

```bash
echo "0 3 * * * certbot renew --quiet && cd /opt/paiement-fisc && docker compose --env-file .env restart nginx" | crontab -
```

---

## Commandes courantes

```bash
cd /opt/paiement-fisc

docker compose --env-file .env ps
docker compose --env-file .env logs -f app
docker compose --env-file .env logs -f worker
docker compose --env-file .env restart app

# Santé
curl http://127.0.0.1:8080/health/ready

# Mise à jour (après git pull ou nouvel upload)
docker compose --env-file .env build app worker
docker compose --env-file .env up -d
docker compose --env-file .env exec app flask db upgrade

# Sauvegarde
bash deploy/hostinger/backup.sh
```

---

## Configuration `.env`

| Variable | Obligatoire | Description |
|----------|-------------|-------------|
| `POSTGRES_PASSWORD` | Oui | Mot de passe PostgreSQL |
| `SECRET_KEY` | Oui | Clé secrète Flask |
| `GOOGLE_MAPS_API_KEY` | Non | Carte Google Maps |
| `SESSION_COOKIE_SECURE` | Non | `true` avec HTTPS (défaut) |
| `GUNICORN_WORKERS` | Non | `2` sur VPS 1–2 Go RAM |
| `HTTP_PORT` | Non | `8080` si port 80 occupé (défaut auto sur Hostinger) |
| `LOG_FORMAT` | Non | `json` en production |
| `REDIS_URL` | Non | Injecté par Docker Compose |

---

## Test local (Docker Desktop)

```powershell
cd "D:\Nos logiciels\Paiement fisc"
copy .env.docker.example .env
# Éditer POSTGRES_PASSWORD et SECRET_KEY
docker compose --env-file .env up --build
```

---

## Dépannage

| Problème | Solution |
|----------|----------|
| `Authentication failed` SSH | hPanel → réinitialiser mot de passe root ou ajouter clé SSH → voir [RELANCE.md](deploy/hostinger/RELANCE.md) |
| Port 80 déjà utilisé (autre app sur le VPS) | `HTTP_PORT=8080` dans `.env`, puis `docker compose up -d` |
| 502 Bad Gateway | `docker compose logs app` — attendre init_db |
| Login impossible | HTTPS actif + `SESSION_COOKIE_SECURE=true` |
| Données manquantes | `verify_migration_status.py` — réimporter pg_dump |

### Déploiement automatisé depuis Windows

```powershell
pip install -r deploy/requirements-deploy.txt
$env:DEPLOY_SSH_PASS = '...'   # session uniquement
$env:DEPLOY_ARCHIVE = "$env:TEMP\paiement-fisc-deploy.tar.gz"
$env:DEPLOY_DUMP_LOCAL = "...\deploy\hostinger\backup.dump"
python deploy/hostinger/remote_deploy.py
```

Voir **[deploy/hostinger/RELANCE.md](deploy/hostinger/RELANCE.md)** si un déploiement a échoué.

---

## Déploiement sans Docker

Voir [DEPLOY.md](DEPLOY.md) (systemd + PostgreSQL natif).

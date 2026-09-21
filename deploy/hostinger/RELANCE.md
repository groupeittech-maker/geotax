# Relance du déploiement Hostinger

Le déploiement automatique a échoué : **authentification SSH refusée** sur `76.13.36.246`.

Le VPS répond déjà avec une autre application (**Mobility Health API**) sur les ports 80/443.
Paiement Fiscal devra utiliser un **autre port** (ex. `8080`) ou remplacer cette app.

---

## Étape 1 — Corriger l'accès SSH (hPanel Hostinger)

1. hPanel → **VPS** → votre serveur → **SSH access**
2. **Option A** : Réinitialiser le mot de passe **root** (copier le nouveau)
3. **Option B** : Ajouter votre clé publique :
   ```powershell
   Get-Content $env:USERPROFILE\.ssh\id_rsa.pub
   ```
   Coller dans « SSH keys » du VPS.

Test :
```powershell
ssh root@76.13.36.246
```

---

## Étape 2 — Préparer localement (déjà fait)

- `deploy/hostinger/backup.dump` — sauvegarde PostgreSQL (~76 Ko)
- Archive projet dans `%TEMP%\paiement-fisc-deploy.tar.gz` (recréer si besoin, voir ci-dessous)

Recréer l'archive :
```powershell
cd "D:\Nos logiciels\Paiement fisc"
tar -czf $env:TEMP\paiement-fisc-deploy.tar.gz --exclude=.env --exclude=.git --exclude=instance --exclude=venv --exclude=__pycache__ -C . .
```

---

## Étape 3 — Déployer (mot de passe **session uniquement**, ne pas committer)

```powershell
cd "D:\Nos logiciels\Paiement fisc"
pip install -r deploy/requirements-deploy.txt

$env:DEPLOY_SSH_PASS = 'VOTRE_NOUVEAU_MOT_DE_PASSE'
$env:DEPLOY_ARCHIVE = "$env:TEMP\paiement-fisc-deploy.tar.gz"
$env:DEPLOY_DUMP_LOCAL = "$PWD\deploy\hostinger\backup.dump"

python deploy/hostinger/remote_deploy.py
```

---

## Étape 4 — Conflit port 80 (Mobility Health déjà installé)

Avant `deploy.sh`, sur le VPS éditez `.env` :
```
HTTP_PORT=8080
```

Puis relancez :
```bash
cd /opt/paiement-fisc
docker compose --env-file .env up -d
```

Accès : **http://76.13.36.246:8080**

---

## Étape 5 — Vérification

```bash
docker compose --env-file .env ps
docker compose --env-file .env exec app python deploy/verify_migration_status.py
```

Connexion : **admin / admin123** — changez le mot de passe immédiatement.

---

## Sécurité

- Ne partagez plus le mot de passe root dans le chat
- Changez le mot de passe root après déploiement
- Préférez une clé SSH à long terme

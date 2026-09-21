# CI/CD — Déploiement automatique

Chaque `push` sur la branche `master` déclenche le pipeline
[`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) :

1. **Vérifications** — compilation Python + validation des templates Jinja.
2. **Synchronisation** — `rsync` du code vers `/opt/paiement-fisc` sur le VPS
   (fichiers sensibles exclus via `deploy/hostinger/rsync-exclude.txt` : `.env`,
   dumps, `qr_codes/`, uploads…).
3. **Redéploiement** — `deploy/hostinger/update-on-server.sh` sur le VPS :
   rebuild des images `app`/`worker`, `docker compose up -d`, migrations
   Alembic, synchronisation PostGIS.
4. **Health check** — `curl http://127.0.0.1:$HTTP_PORT/health/ready` sur le VPS.

Déclenchement manuel possible : onglet **Actions → CI/CD GeoTax → Run workflow**.

## Secrets GitHub requis

Définis dans *Settings → Secrets and variables → Actions* :

| Secret | Valeur |
|--------|--------|
| `VPS_SSH_KEY` | Clé privée SSH du compte de déploiement |
| `VPS_HOST` | `76.13.36.246` |
| `VPS_USER` | `root` |
| `VPS_PORT` | `22` |
| `APP_DIR` | `/opt/paiement-fisc` |

## Clé SSH de déploiement

Une clé dédiée (`github-actions-geotax`) est installée dans
`/root/.ssh/authorized_keys` sur le VPS. La clé privée correspondante est
stockée dans le secret `VPS_SSH_KEY` (et une copie locale dans
`~/.ssh/geotax_cicd`).

Pour regénérer / réinstaller la clé :

```bash
ssh-keygen -t ed25519 -f ~/.ssh/geotax_cicd -N "" -C "github-actions-geotax"
ssh root@76.13.36.246 "echo '$(cat ~/.ssh/geotax_cicd.pub)' >> ~/.ssh/authorized_keys"
gh secret set VPS_SSH_KEY < ~/.ssh/geotax_cicd   # depuis la racine du repo
```

## Rollback

Le déploiement est file-based : pour revenir en arrière, pousser le commit
précédent (`git revert` + `push`) relancera le pipeline avec l'ancien code.

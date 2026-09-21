# Système de Paiement Fiscal via QR Code + SMS USSD

Système ultra-léger pour la gestion des paiements fiscaux des boutiques via QR Code et paiements USSD/Mobile Money.

## Fonctionnalités

- ✅ QR Code unique par boutique
- ✅ Paiement via USSD (*123*IDBOUTIQUE*Montant#)
- ✅ Paiement via Mobile Money (MTN/Airtel)
- ✅ Tableau de bord web pour les Impôts
- ✅ Contrôle sur le terrain avec scan QR code
- ✅ Rapports et exports Excel

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

1. Copier `.env.example` vers `.env`
2. Renseigner les variables dans `.env` :
   - `DATABASE_URL` : PostgreSQL (**obligatoire**)
   - `SECRET_KEY` : clé secrète Flask
   - `GOOGLE_MAPS_API_KEY` : optionnel (carte Google Maps)
3. Vérifier : `python deploy/verify_migration_status.py`
4. Installer : `pip install -r requirements.txt`
5. Lancer : `python app.py` (avec `DATABASE_URL` définie)

### Production (VPS)

**Docker + Hostinger (recommandé)** : **[DEPLOY_HOSTINGER.md](DEPLOY_HOSTINGER.md)**

```bash
sudo bash deploy/hostinger/install-docker.sh
cp .env.docker.example .env
sudo bash deploy/hostinger/deploy.sh
```

**Sans Docker** : **[DEPLOY.md](DEPLOY.md)**

### Google Maps

1. Créer un projet sur [Google Cloud Console](https://console.cloud.google.com/)
2. Activer **Maps JavaScript API**
3. Créer une clé API (Credentials → Create credentials → API key)
4. Ajouter la clé dans `.env` : `GOOGLE_MAPS_API_KEY=votre_cle`
5. Redémarrer l'application

## Structure du Projet

- `app.py` : Application Flask principale
- `models.py` : Modèles de base de données
- `routes/` : Routes API et web
- `static/` : Fichiers CSS, JS, images
- `templates/` : Templates HTML
- `qr_codes/` : QR codes générés pour les boutiques
- `DEPLOY.md` : index déploiement (PostgreSQL)
- `DEPLOY_HOSTINGER.md` : Docker sur VPS Hostinger
- PostgreSQL : base de données unique (voir `DATABASE_URL` dans `.env`)

## Utilisation

### Pour les commerçants
- Scanner le QR code de leur boutique
- Payer via USSD : *123*IDBOUTIQUE*Montant#
- Payer via Mobile Money avec référence boutique

### Pour les contrôleurs
- Scanner le QR code d'une boutique
- Voir immédiatement le statut de paiement

### Pour les administrateurs
- Accéder au tableau de bord web
- Voir les rapports par arrondissement/zone
- Exporter les données en Excel


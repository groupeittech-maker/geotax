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

1. Créer un fichier `.env` (optionnel) pour les configurations
2. Lancer l'application : `python app.py`

## Structure du Projet

- `app.py` : Application Flask principale
- `models.py` : Modèles de base de données
- `routes/` : Routes API et web
- `static/` : Fichiers CSS, JS, images
- `templates/` : Templates HTML
- `qr_codes/` : QR codes générés pour les boutiques
- `database.db` : Base de données SQLite

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


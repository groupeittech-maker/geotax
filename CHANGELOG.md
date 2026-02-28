# Historique des versions

## [1.0.0] - 2026-02-28

### Fonctionnalités principales
- Gestion des commerces avec QR code unique
- Paiements via USSD et Mobile Money (webhooks)
- Numéro de transaction unique (TXN-YYYY-NNNNNN) pour chaque paiement
- Reçu de paiement avec QR code de vérification
- Statut « à jour » : toutes les taxes du mois doivent être payées
- Balances par taxes (affichage en cartes)
- Espace commerçant (connexion, paiement, historique)
- Contrôle sur le terrain (scan QR code)
- Gestion des rôles (agent terrain, agent financier, conseiller municipal, admin)
- Paramétrage géographique (pays, départements, communes, quartiers)
- Export Excel
- Carte des commerces

### Pile technologique
- Python, Flask, SQLAlchemy, SQLite
- HTML/CSS/JavaScript
- qrcode, Pillow, openpyxl

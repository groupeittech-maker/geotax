# Guide de Démarrage Rapide

## Installation

### 1. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 2. Lancer l'application

```bash
python app.py
```

L'application sera accessible sur: `http://localhost:5000`

## Utilisation

### Pour les Administrateurs

1. **Accéder au tableau de bord**: `http://localhost:5000`
2. **Ajouter une boutique**: Aller dans "Boutiques" → Remplir le formulaire → Le QR code est généré automatiquement
3. **Voir les statistiques**: Le tableau de bord affiche les statistiques en temps réel
4. **Exporter en Excel**: Cliquer sur "📊 Exporter Excel" pour télécharger un rapport

### Pour les Contrôleurs

1. **Scanner un QR code**: Aller sur `http://localhost:5000/scan`
2. **Saisir le code boutique** ou scanner le QR code avec l'appareil photo
3. **Voir le statut** immédiatement: ✅ PAYÉ ou ❌ NON PAYÉ

### Pour les Commerçants

#### Paiement via USSD

1. Composer sur le téléphone: `*123*CODE_BOUTIQUE*MONTANT#`
2. Exemple: `*123*BOUTIQUE-57891*5000#`
3. Le paiement est automatiquement enregistré

#### Paiement via Mobile Money

1. Ouvrir l'application Mobile Money (MTN/Airtel)
2. Effectuer un paiement marchand vers "IMPOTS"
3. Dans le champ référence/message, saisir: `CODE_BOUTIQUE`
4. Exemple: `BOUTIQUE-57891`
5. Le paiement est automatiquement enregistré

## Structure des Fichiers

```
Paiement fisc/
├── app.py                 # Application Flask principale
├── models.py              # Modèles de base de données
├── requirements.txt       # Dépendances Python
├── test_system.py         # Script de test
├── example_webhook.py     # Exemple d'intégration webhook
├── templates/             # Templates HTML
│   ├── dashboard.html    # Tableau de bord
│   ├── scan.html         # Page de scan QR code
│   └── boutiques.html    # Gestion des boutiques
├── static/               # Fichiers statiques
│   └── style.css         # Styles CSS
├── qr_codes/             # QR codes générés (créé automatiquement)
└── database.db           # Base de données SQLite (créée automatiquement)
```

## API Endpoints

### Boutiques

- `GET /api/boutiques` - Liste des boutiques (avec filtres)
- `POST /api/boutiques` - Créer une boutique
- `GET /api/boutiques/<id>/qr` - Récupérer le QR code

### Paiements

- `POST /api/paiements/ussd` - Recevoir un paiement USSD
- `POST /api/paiements/mobile-money` - Recevoir un paiement Mobile Money

### Scan

- `GET /api/scan/<code_boutique>` - Vérifier le statut d'une boutique

### Statistiques

- `GET /api/statistiques` - Récupérer les statistiques globales

### Export

- `GET /api/export/excel` - Exporter les données en Excel

## Tests

### Tester le système

```bash
# Démarrer l'application dans un terminal
python app.py

# Dans un autre terminal, lancer les tests
python test_system.py
```

### Tester les webhooks

```bash
python example_webhook.py
```

## Exemples d'Utilisation

### Créer une boutique via API

```bash
curl -X POST http://localhost:5000/api/boutiques \
  -H "Content-Type: application/json" \
  -d '{
    "nom": "Boutique Test",
    "proprietaire": "Jean Dupont",
    "arrondissement": "Arrondissement 1",
    "zone": "Zone A"
  }'
```

### Simuler un paiement USSD

```bash
curl -X POST http://localhost:5000/api/paiements/ussd \
  -H "Content-Type: application/json" \
  -d '{
    "code_boutique": "BOUTIQUE-57891",
    "montant": 5000,
    "numero_telephone": "+237 6XX XXX XXX"
  }'
```

### Vérifier le statut d'une boutique

```bash
curl http://localhost:5000/api/scan/BOUTIQUE-57891
```

## Personnalisation

### Modifier le montant fiscal par défaut

Dans `app.py`, vous pouvez modifier la configuration:

```python
Configuration.set('montant_fiscal_mensuel', '5000', 'Montant fiscal mensuel par défaut')
```

### Modifier le code USSD

```python
Configuration.set('code_ussd', '*123#', 'Code USSD pour les paiements')
```

## Déploiement en Production

Voir le fichier `INTEGRATION.md` pour les détails sur:
- Intégration avec les opérateurs télécoms
- Configuration HTTPS
- Déploiement avec Gunicorn
- Migration vers PostgreSQL/MySQL

## Support

Pour toute question ou problème, consultez:
- `README.md` - Documentation générale
- `INTEGRATION.md` - Guide d'intégration avec les opérateurs
- Code source commenté dans `app.py` et `models.py`


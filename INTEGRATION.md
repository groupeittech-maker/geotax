# Guide d'Intégration - Système de Paiement Fiscal

## Intégration avec les Opérateurs Télécoms

### 1. Intégration USSD

Pour intégrer le système avec les opérateurs télécoms (MTN, Airtel), vous devez configurer un code USSD.

#### Format du Code USSD

```
*123*CODE_BOUTIQUE*MONTANT#
```

Exemple:
```
*123*BOUTIQUE-57891*5000#
```

#### Configuration côté Opérateur

1. **Contacter l'opérateur** (MTN/Airtel) pour obtenir un code USSD dédié
2. **Configurer le callback** vers votre API:
   ```
   POST http://votre-serveur.com/api/paiements/ussd
   ```

#### Format des données reçues

L'opérateur doit envoyer les données suivantes:

```json
{
  "code_boutique": "BOUTIQUE-57891",
  "montant": 5000,
  "numero_telephone": "+237 6XX XXX XXX",
  "reference_transaction": "USSD-20240101120000-12345"
}
```

### 2. Intégration Mobile Money

#### MTN Mobile Money

1. **S'inscrire au programme MTN Mobile Money API**
2. **Configurer les webhooks** pour recevoir les notifications de paiement
3. **Format du message**:
   - Le commerçant envoie le code boutique dans le champ "Référence" ou "Message"
   - Exemple: "BOUTIQUE-57891"

#### Airtel Money

1. **S'inscrire au programme Airtel Money API**
2. **Configurer les webhooks** similaires à MTN
3. **Format identique** à MTN

#### Webhook de Notification

L'opérateur doit envoyer une requête POST vers:

```
POST http://votre-serveur.com/api/paiements/mobile-money
```

**Format des données:**

```json
{
  "code_boutique": "BOUTIQUE-57891",
  "montant": 5000,
  "numero_telephone": "+237 6XX XXX XXX",
  "operateur": "MTN",
  "reference_transaction": "MTN-20240101120000-67890"
}
```

### 3. Exemple d'Intégration avec Flask

```python
@app.route('/api/paiements/mobile-money', methods=['POST'])
def receive_mobile_money_payment():
    # Vérifier l'authentification (token, signature, etc.)
    auth_token = request.headers.get('Authorization')
    if not verify_webhook_signature(auth_token):
        return jsonify({'error': 'Non autorisé'}), 401
    
    # Traiter le paiement
    data = request.json
    # ... reste du code
```

### 4. Sécurité

- **Authentification**: Utiliser des tokens API ou signatures HMAC
- **HTTPS**: Toujours utiliser HTTPS en production
- **Validation**: Vérifier les montants et références de transaction
- **Idempotence**: Vérifier que les transactions ne sont pas dupliquées

### 5. Test en Local

Pour tester sans intégration réelle avec les opérateurs:

```bash
# Simuler un paiement USSD
curl -X POST http://localhost:5000/api/paiements/ussd \
  -H "Content-Type: application/json" \
  -d '{
    "code_boutique": "BOUTIQUE-57891",
    "montant": 5000,
    "numero_telephone": "+237 6XX XXX XXX"
  }'

# Simuler un paiement Mobile Money
curl -X POST http://localhost:5000/api/paiements/mobile-money \
  -H "Content-Type: application/json" \
  -d '{
    "code_boutique": "BOUTIQUE-57891",
    "montant": 5000,
    "numero_telephone": "+237 6XX XXX XXX",
    "operateur": "MTN",
    "reference_transaction": "MTN-TEST-123"
  }'
```

## Déploiement

### Production

1. **Serveur Web**: Utiliser Gunicorn ou uWSGI
   ```bash
   pip install gunicorn
   gunicorn -w 4 -b 0.0.0.0:5000 app:app
   ```

2. **Base de données** : PostgreSQL (`DATABASE_URL` dans `.env`)

3. **Vérifier la migration** :
   ```bash
   python deploy/verify_migration_status.py
   python deploy/verify_postgres.py
   ```

4. **Legacy — migration SQLite** (une seule fois, si jamais fait) :
   ```bash
   python deploy/migrate_sqlite_to_postgres.py --sqlite instance/database.db
   ```

3. **HTTPS**: Configurer un certificat SSL (Let's Encrypt)

4. **Backup**: Mettre en place des sauvegardes régulières de la base de données

### Variables d'Environnement

Créer un fichier `.env`:

```
FLASK_ENV=production
DATABASE_URL=postgresql://user:password@localhost/paiement_fisc
SECRET_KEY=your-secret-key-here
```


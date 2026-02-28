"""
Exemple de webhook pour simuler les notifications des opérateurs télécoms
Ce fichier montre comment les opérateurs doivent envoyer les données
"""

import requests
import json
from datetime import datetime

# URL de votre serveur
API_URL = "http://localhost:5000"

def simulate_ussd_payment(code_boutique, montant, numero_telephone):
    """
    Simule un paiement USSD
    C'est ainsi que l'opérateur télécom devrait appeler votre API
    """
    url = f"{API_URL}/api/paiements/ussd"
    
    data = {
        "code_boutique": code_boutique,
        "montant": montant,
        "numero_telephone": numero_telephone,
        "reference_transaction": f"USSD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{numero_telephone[-4:]}"
    }
    
    headers = {
        "Content-Type": "application/json",
        # En production, ajouter un token d'authentification
        # "Authorization": "Bearer YOUR_API_TOKEN"
    }
    
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 201:
            print(f"✅ Paiement USSD simulé avec succès")
            print(f"   Référence: {data['reference_transaction']}")
            return response.json()
        else:
            print(f"❌ Erreur: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Erreur de connexion: {e}")
        return None


def simulate_mobile_money_payment(code_boutique, montant, numero_telephone, operateur="MTN"):
    """
    Simule un paiement Mobile Money
    C'est ainsi que l'opérateur télécom devrait appeler votre API via webhook
    """
    url = f"{API_URL}/api/paiements/mobile-money"
    
    data = {
        "code_boutique": code_boutique,
        "montant": montant,
        "numero_telephone": numero_telephone,
        "operateur": operateur,
        "reference_transaction": f"{operateur}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{numero_telephone[-4:]}"
    }
    
    headers = {
        "Content-Type": "application/json",
        # En production, ajouter une signature HMAC pour vérifier l'authenticité
        # "X-Webhook-Signature": calculate_hmac_signature(data, secret_key)
    }
    
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 201:
            print(f"✅ Paiement {operateur} Money simulé avec succès")
            print(f"   Référence: {data['reference_transaction']}")
            return response.json()
        else:
            print(f"❌ Erreur: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Erreur de connexion: {e}")
        return None


def verify_webhook_signature(data, signature, secret_key):
    """
    Exemple de vérification de signature HMAC pour sécuriser les webhooks
    """
    import hmac
    import hashlib
    
    # Créer la signature attendue
    message = json.dumps(data, sort_keys=True)
    expected_signature = hmac.new(
        secret_key.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # Comparer avec la signature reçue
    return hmac.compare_digest(expected_signature, signature)


if __name__ == "__main__":
    print("=" * 60)
    print("📱 SIMULATION DE PAIEMENTS TÉLÉCOMS")
    print("=" * 60)
    
    # Exemple d'utilisation
    code_boutique = "BOUTIQUE-57891"
    montant = 5000
    numero = "+237 6XX XXX XXX"
    
    print("\n1. Simulation paiement USSD:")
    simulate_ussd_payment(code_boutique, montant, numero)
    
    print("\n2. Simulation paiement MTN Money:")
    simulate_mobile_money_payment(code_boutique, montant, numero, "MTN")
    
    print("\n3. Simulation paiement Airtel Money:")
    simulate_mobile_money_payment(code_boutique, montant, numero, "AIRTEL")
    
    print("\n" + "=" * 60)
    print("✅ Simulations terminées!")
    print("=" * 60)


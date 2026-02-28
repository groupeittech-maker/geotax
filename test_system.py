"""
Script de test pour le système de paiement fiscal
Permet de tester les fonctionnalités principales
"""

import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:5000"

def test_create_boutique():
    """Test de création d'une boutique"""
    print("\n🔹 Test: Création d'une boutique")
    
    data = {
        "nom": "Boutique Test",
        "proprietaire": "Jean Dupont",
        "telephone": "+237 6XX XXX XXX",
        "adresse": "Rue principale, Marché Central",
        "arrondissement": "Arrondissement 1",
        "zone": "Zone A",
        "marche": "Marché Central"
    }
    
    response = requests.post(f"{BASE_URL}/api/boutiques", json=data)
    
    if response.status_code == 201:
        boutique = response.json()
        print(f"✅ Boutique créée: {boutique['code_unique']}")
        return boutique['code_unique']
    else:
        print(f"❌ Erreur: {response.text}")
        return None

def test_ussd_payment(code_boutique):
    """Test de paiement USSD"""
    print(f"\n🔹 Test: Paiement USSD pour {code_boutique}")
    
    data = {
        "code_boutique": code_boutique,
        "montant": 5000,
        "numero_telephone": "+237 6XX XXX XXX",
        "reference_transaction": f"USSD-TEST-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    }
    
    response = requests.post(f"{BASE_URL}/api/paiements/ussd", json=data)
    
    if response.status_code == 201:
        result = response.json()
        print(f"✅ Paiement enregistré: {result['paiement']['reference_transaction']}")
        return True
    else:
        print(f"❌ Erreur: {response.text}")
        return False

def test_mobile_money_payment(code_boutique):
    """Test de paiement Mobile Money"""
    print(f"\n🔹 Test: Paiement Mobile Money pour {code_boutique}")
    
    data = {
        "code_boutique": code_boutique,
        "montant": 5000,
        "numero_telephone": "+237 6XX XXX XXX",
        "operateur": "MTN",
        "reference_transaction": f"MTN-TEST-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    }
    
    response = requests.post(f"{BASE_URL}/api/paiements/mobile-money", json=data)
    
    if response.status_code == 201:
        result = response.json()
        print(f"✅ Paiement enregistré: {result['paiement']['reference_transaction']}")
        return True
    else:
        print(f"❌ Erreur: {response.text}")
        return False

def test_scan_boutique(code_boutique):
    """Test de scan QR code"""
    print(f"\n🔹 Test: Scan QR code pour {code_boutique}")
    
    response = requests.get(f"{BASE_URL}/api/scan/{code_boutique}")
    
    if response.status_code == 200:
        data = response.json()
        statut = "✅ PAYÉ" if data['statut_paiement'] == 'PAYE' else "❌ NON PAYÉ"
        print(f"{statut} - Boutique: {data['boutique']['nom']}")
        print(f"   Dernier paiement: {data.get('dernier_paiement', {}).get('date_paiement', 'Aucun')}")
        return True
    else:
        print(f"❌ Erreur: {response.text}")
        return False

def test_statistiques():
    """Test des statistiques"""
    print("\n🔹 Test: Récupération des statistiques")
    
    response = requests.get(f"{BASE_URL}/api/statistiques")
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Statistiques récupérées:")
        print(f"   Total boutiques: {data['total_boutiques']}")
        print(f"   À jour: {data['boutiques_a_jour']}")
        print(f"   Non à jour: {data['boutiques_non_a_jour']}")
        print(f"   Taux de paiement: {data['taux_paiement']}%")
        print(f"   Total collecté: {data['total_paiements_mois']} FCFA")
        return True
    else:
        print(f"❌ Erreur: {response.text}")
        return False

def main():
    """Exécuter tous les tests"""
    print("=" * 60)
    print("🧪 TESTS DU SYSTÈME DE PAIEMENT FISCAL")
    print("=" * 60)
    
    try:
        # Test de création de boutique
        code_boutique = test_create_boutique()
        
        if code_boutique:
            # Test de scan
            test_scan_boutique(code_boutique)
            
            # Test de paiement USSD
            test_ussd_payment(code_boutique)
            
            # Test de scan après paiement
            test_scan_boutique(code_boutique)
            
            # Test de paiement Mobile Money
            test_mobile_money_payment(code_boutique)
            
            # Test des statistiques
            test_statistiques()
        
        print("\n" + "=" * 60)
        print("✅ Tests terminés!")
        print("=" * 60)
        
    except requests.exceptions.ConnectionError:
        print("\n❌ Erreur: Impossible de se connecter au serveur.")
        print("   Assurez-vous que l'application Flask est démarrée:")
        print("   python app.py")
    except Exception as e:
        print(f"\n❌ Erreur inattendue: {e}")

if __name__ == "__main__":
    main()


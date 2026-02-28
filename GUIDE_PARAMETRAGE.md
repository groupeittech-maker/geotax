# Guide de Paramétrage Géographique

## Vue d'ensemble

Le système permet de gérer une hiérarchie géographique complète :
- **Pays** → **Départements** → **Communes** → **Quartiers/Villages**

Cette hiérarchie permet une organisation précise des boutiques et des statistiques.

## Structure Hiérarchique

```
Pays
  └── Département
      └── Commune
          └── Quartier/Village
              └── Boutique
```

## Configuration Initiale

### 1. Créer les Pays

1. Aller dans **Paramétrage** → Onglet **Pays**
2. Cliquer sur **"➕ Ajouter un Pays"**
3. Remplir :
   - **Code** : Code unique (ex: CMR, FRA)
   - **Nom** : Nom du pays (ex: Cameroun, France)
   - **Code ISO** : Code ISO à 3 lettres (optionnel)
4. Cliquer sur **"Enregistrer"**

**Exemple :**
- Code: `CMR`
- Nom: `Cameroun`
- Code ISO: `CMR`

### 2. Créer les Départements

1. Aller dans **Paramétrage** → Onglet **Départements**
2. Cliquer sur **"➕ Ajouter un Département"**
3. Remplir :
   - **Pays** : Sélectionner le pays
   - **Code** : Code unique du département (ex: 001, 002)
   - **Nom** : Nom du département
4. Cliquer sur **"Enregistrer"**

**Exemple :**
- Pays: `Cameroun`
- Code: `001`
- Nom: `Département du Littoral`

### 3. Créer les Communes

1. Aller dans **Paramétrage** → Onglet **Communes**
2. Cliquer sur **"➕ Ajouter une Commune"**
3. Remplir :
   - **Département** : Sélectionner le département
   - **Code** : Code unique de la commune (ex: 001, 002)
   - **Nom** : Nom de la commune
4. Cliquer sur **"Enregistrer"**

**Exemple :**
- Département: `Département du Littoral`
- Code: `001`
- Nom: `Commune de Douala`

### 4. Créer les Quartiers/Villages

1. Aller dans **Paramétrage** → Onglet **Quartiers/Villages**
2. Cliquer sur **"➕ Ajouter un Quartier/Village"**
3. Remplir :
   - **Commune** : Sélectionner la commune
   - **Type** : Choisir "Quartier" ou "Village"
   - **Code** : Code unique (ex: 001, 002)
   - **Nom** : Nom du quartier ou village
4. Cliquer sur **"Enregistrer"**

**Exemple :**
- Commune: `Commune de Douala`
- Type: `Quartier`
- Code: `001`
- Nom: `Quartier Bonanjo`

## Utilisation lors de la Création d'une Boutique

Lors de la création d'une boutique :

1. **Sélectionner le Quartier/Village** (obligatoire)
   - Le système affiche : `Nom (Type) - Commune - Département - Pays`
   - Exemple : `Bonanjo (quartier) - Commune de Douala - Département du Littoral - Cameroun`

2. **Nom du Marché** (optionnel)
   - Si la boutique est dans un marché spécifique
   - Exemple : `Marché Central`, `Marché de Mokolo`

3. **Anciens champs** (optionnels - pour compatibilité)
   - Arrondissement, Zone, Marché
   - Conservés pour les boutiques existantes

## Avantages de cette Hiérarchie

### 1. Organisation Précise
- Chaque boutique est localisée précisément
- Facilite les recherches et filtres

### 2. Statistiques Détaillées
- Statistiques par pays
- Statistiques par département
- Statistiques par commune
- Statistiques par quartier/village

### 3. Rapports Structurés
- Export Excel avec hiérarchie complète
- Filtres par niveau géographique

### 4. Évolutivité
- Facile d'ajouter de nouveaux niveaux
- Compatible avec les anciennes données

## Migration des Données Existantes

Si vous avez déjà des boutiques avec les anciens champs (arrondissement, zone, marché) :

1. **Option 1 : Conserver les anciens champs**
   - Les boutiques existantes continuent de fonctionner
   - Les nouveaux champs sont optionnels

2. **Option 2 : Migrer vers la nouvelle hiérarchie**
   - Créer les entités géographiques correspondantes
   - Mettre à jour les boutiques une par une
   - Ou créer un script de migration

## Bonnes Pratiques

### Codes Uniques
- Utiliser des codes courts et significatifs
- Exemples : `001`, `CMR`, `DOU-001`

### Noms
- Utiliser des noms complets et officiels
- Éviter les abréviations dans les noms

### Organisation
- Commencer par créer tous les pays
- Puis tous les départements
- Puis toutes les communes
- Enfin tous les quartiers/villages

### Vérification
- Vérifier qu'il n'y a pas de doublons
- Le système empêche les codes en double au même niveau

## Dépannage

### "Pays non trouvé" lors de la création d'un département
- Vérifier que le pays a été créé au préalable
- Vérifier que le pays est actif

### "Département non trouvé" lors de la création d'une commune
- Vérifier que le département a été créé au préalable
- Vérifier que le département est actif

### "Commune non trouvée" lors de la création d'un quartier
- Vérifier que la commune a été créée au préalable
- Vérifier que la commune est active

### Impossible de sélectionner un quartier lors de la création d'une boutique
- Vérifier que la hiérarchie complète est créée (Pays → Département → Commune → Quartier)
- Vérifier que tous les éléments sont actifs

## API Disponibles

Toutes les opérations sont disponibles via l'API :

- `GET /api/pays` - Liste des pays
- `POST /api/pays` - Créer un pays
- `PUT /api/pays/<id>` - Modifier un pays
- `DELETE /api/pays/<id>` - Désactiver un pays

- `GET /api/departements?pays_id=X` - Liste des départements
- `POST /api/departements` - Créer un département
- `PUT /api/departements/<id>` - Modifier un département
- `DELETE /api/departements/<id>` - Désactiver un département

- `GET /api/communes?departement_id=X` - Liste des communes
- `POST /api/communes` - Créer une commune
- `PUT /api/communes/<id>` - Modifier une commune
- `DELETE /api/communes/<id>` - Désactiver une commune

- `GET /api/quartiers-villages?commune_id=X` - Liste des quartiers/villages
- `POST /api/quartiers-villages` - Créer un quartier/village
- `PUT /api/quartiers-villages/<id>` - Modifier un quartier/village
- `DELETE /api/quartiers-villages/<id>` - Désactiver un quartier/village


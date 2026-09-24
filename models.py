from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json
import os

db = SQLAlchemy()

# Données par défaut pour l'initialisation (seed) — remplacées en base au paramétrage
DEFAULT_NATURES_POI = [
    {
        'code': 'ecole',
        'nom': 'École',
        'ordre': 1,
        'mots_cles': [
            'auto ecole', 'auto-ecole', 'autoecole', 'ecole', 'school', 'scolar',
            'enseignement', 'universite', 'univ ', 'lycee', 'college', 'colleg',
            'maternel', 'education', 'pedagog', 'institut',
        ],
        'champs': [
            {'code': 'nb_eleves', 'libelle': "Nombre d'élèves", 'type_champ': 'int', 'placeholder': 'ex. 240', 'ordre': 1},
            {'code': 'nb_professeurs', 'libelle': "Nombre d'enseignants", 'type_champ': 'int', 'placeholder': 'ex. 12', 'ordre': 2},
            {'code': 'niveaux_scolaires', 'libelle': 'Niveaux / cycles', 'type_champ': 'str', 'placeholder': 'Maternelle, primaire, secondaire…', 'ordre': 3, 'pleine_largeur': True},
            {'code': 'remarques', 'libelle': 'Remarques', 'type_champ': 'textarea', 'placeholder': 'Infrastructure, agrément, etc.', 'ordre': 4, 'pleine_largeur': True},
        ],
    },
    {
        'code': 'restaurant',
        'nom': 'Restaurant',
        'ordre': 2,
        'mots_cles': ['rst', 'restaurant', 'resto', 'cafet', 'cafe', 'brasser'],
        'champs': [
            {'code': 'capacite_accueil', 'libelle': "Capacité d'accueil (couverts)", 'type_champ': 'int', 'ordre': 1},
            {'code': 'nb_tables', 'libelle': 'Nombre de tables', 'type_champ': 'int', 'ordre': 2},
            {'code': 'surface_m2', 'libelle': 'Surface (m²)', 'type_champ': 'float', 'ordre': 3},
            {'code': 'numero_agrement_sanitaire', 'libelle': 'N° agrément sanitaire (si applicable)', 'type_champ': 'str', 'ordre': 4, 'pleine_largeur': True},
        ],
    },
    {
        'code': 'vehicule',
        'nom': 'Véhicule / transport',
        'ordre': 3,
        'mots_cles': ['transport', 'taxi', 'vehicule', 'voiture', 'bus', 'automobile'],
        'champs': [
            {'code': 'immatriculation_principale', 'libelle': 'Immatriculation principale', 'type_champ': 'str', 'placeholder': 'ex. XYZ-123-AB', 'ordre': 1},
            {'code': 'nb_unites', 'libelle': "Nombre d'unités (véhicules)", 'type_champ': 'int', 'ordre': 2},
            {'code': 'capacite_passagers', 'libelle': 'Capacité passagers', 'type_champ': 'int', 'ordre': 3},
            {'code': 'remarques', 'libelle': 'Remarques', 'type_champ': 'textarea', 'ordre': 4, 'pleine_largeur': True},
        ],
    },
    {
        'code': 'station_lavage',
        'nom': 'Station de lavage',
        'ordre': 4,
        'mots_cles': ['lavage', 'laverie', 'station lavage'],
        'champs': [
            {'code': 'nb_postes_lavage', 'libelle': 'Nombre de postes de lavage', 'type_champ': 'int', 'ordre': 1},
            {'code': 'surface_m2', 'libelle': 'Surface (m²)', 'type_champ': 'float', 'ordre': 2},
            {'code': 'remarques', 'libelle': 'Remarques', 'type_champ': 'textarea', 'ordre': 3, 'pleine_largeur': True},
        ],
    },
    {
        'code': 'autre',
        'nom': 'Autre',
        'ordre': 99,
        'mots_cles': [],
        'champs': [
            {'code': 'description', 'libelle': 'Description libre', 'type_champ': 'textarea', 'placeholder': "Préciser l'usage, l'effectif, etc.", 'ordre': 1, 'pleine_largeur': True},
        ],
    },
]


class NaturePoi(db.Model):
    """Nature géo-statistique d'un POI (paramétrable)"""
    __tablename__ = 'natures_poi'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False, index=True)
    nom = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    mots_cles = db.Column(db.Text)  # JSON : mots-clés pour inférer depuis le type d'activité
    ordre = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    champs = db.relationship(
        'ChampPoi',
        backref='nature_poi',
        lazy=True,
        cascade='all, delete-orphan',
        order_by='ChampPoi.ordre',
    )

    def get_mots_cles_list(self):
        if not self.mots_cles:
            return []
        try:
            data = json.loads(self.mots_cles)
            return [str(x).strip().lower() for x in data if str(x).strip()]
        except (json.JSONDecodeError, TypeError):
            return []

    def set_mots_cles_list(self, keywords):
        cleaned = [str(k).strip().lower() for k in (keywords or []) if str(k).strip()]
        self.mots_cles = json.dumps(cleaned, ensure_ascii=False)

    def get_champs_actifs(self):
        return [c for c in self.champs if c.active]

    @classmethod
    def get_by_code(cls, code):
        if not code:
            return None
        return cls.query.filter_by(code=str(code).strip().lower(), active=True).first()

    @classmethod
    def get_label_for_code(cls, code):
        n = cls.get_by_code(code)
        if n:
            return n.nom
        fallback = cls.get_by_code('autre')
        return fallback.nom if fallback else str(code or 'Autre')

    @classmethod
    def get_active_codes(cls):
        return {n.code for n in cls.query.filter_by(active=True).all()}

    @classmethod
    def normalize_code(cls, val):
        code = (val or 'autre').strip().lower() if isinstance(val, str) else 'autre'
        if not code:
            code = 'autre'
        if code in cls.get_active_codes():
            return code
        return 'autre' if 'autre' in cls.get_active_codes() else code

    def to_dict(self, include_champs=True):
        result = {
            'id': self.id,
            'code': self.code,
            'nom': self.nom,
            'description': self.description,
            'mots_cles': self.get_mots_cles_list(),
            'ordre': self.ordre,
            'active': self.active,
            'date_creation': self.date_creation.isoformat() if self.date_creation else None,
        }
        if include_champs:
            result['champs'] = [c.to_dict() for c in self.get_champs_actifs()]
        return result


class ChampPoi(db.Model):
    """Champ technique associé à un type d'activité (ou legacy : nature POI)"""
    __tablename__ = 'champs_poi'

    id = db.Column(db.Integer, primary_key=True)
    nature_poi_id = db.Column(db.Integer, db.ForeignKey('natures_poi.id'), nullable=True)
    type_commerce_id = db.Column(db.Integer, db.ForeignKey('types_commerce.id'), nullable=True)
    code = db.Column(db.String(60), nullable=False)
    libelle = db.Column(db.String(200), nullable=False)
    type_champ = db.Column(db.String(20), default='str')  # voir CHAMP_POI_TYPES dans app.py
    placeholder = db.Column(db.String(300))
    ordre = db.Column(db.Integer, default=0)
    pleine_largeur = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)

    type_commerce = db.relationship('TypeCommerce', back_populates='champs', foreign_keys=[type_commerce_id])

    def to_dict(self):
        return {
            'id': self.id,
            'nature_poi_id': self.nature_poi_id,
            'type_commerce_id': self.type_commerce_id,
            'code': self.code,
            'libelle': self.libelle,
            'type_champ': self.type_champ,
            'placeholder': self.placeholder,
            'ordre': self.ordre,
            'pleine_largeur': self.pleine_largeur,
            'active': self.active,
        }


class Institut(db.Model):
    """Modèle pour les institutions de paiement (Impôts, Police, Mairies, etc.)"""
    __tablename__ = 'instituts'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    nom = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(50))  # 'impots', 'police', 'mairie', 'autre'
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    paiements = db.relationship('Paiement', backref='institut', lazy=True)
    taxes = db.relationship('Taxe', backref='institut', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'nom': self.nom,
            'type': self.type,
            'description': self.description,
            'active': self.active,
            'date_creation': self.date_creation.isoformat() if self.date_creation else None
        }


class Pays(db.Model):
    """Modèle pour les pays"""
    __tablename__ = 'pays'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False, index=True)
    nom = db.Column(db.String(100), nullable=False)
    code_iso = db.Column(db.String(3))  # Code ISO (ex: CMR, FRA)
    center_lat = db.Column(db.Float)  # Centre carte (défaut)
    center_lng = db.Column(db.Float)
    default_zoom = db.Column(db.Integer, default=6)
    active = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    departements = db.relationship('Departement', backref='pays', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'nom': self.nom,
            'code_iso': self.code_iso,
            'center_lat': self.center_lat,
            'center_lng': self.center_lng,
            'default_zoom': self.default_zoom,
            'active': self.active,
        }


class Departement(db.Model):
    """Modèle pour les départements"""
    __tablename__ = 'departements'
    
    id = db.Column(db.Integer, primary_key=True)
    pays_id = db.Column(db.Integer, db.ForeignKey('pays.id'), nullable=False)
    code = db.Column(db.String(20), nullable=False, index=True)
    nom = db.Column(db.String(100), nullable=False)
    active = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    communes = db.relationship('Commune', backref='departement', lazy=True, cascade='all, delete-orphan')
    
    # Index composite pour éviter les doublons
    __table_args__ = (db.UniqueConstraint('pays_id', 'code', name='uq_departement_pays_code'),)
    
    def to_dict(self):
        return {
            'id': self.id,
            'pays_id': self.pays_id,
            'pays_nom': self.pays.nom if self.pays else None,
            'code': self.code,
            'nom': self.nom,
            'active': self.active
        }


class Commune(db.Model):
    """Modèle pour les communes"""
    __tablename__ = 'communes'
    
    id = db.Column(db.Integer, primary_key=True)
    departement_id = db.Column(db.Integer, db.ForeignKey('departements.id'), nullable=False)
    code = db.Column(db.String(20), nullable=False, index=True)
    nom = db.Column(db.String(100), nullable=False)
    active = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    quartiers = db.relationship('QuartierVillage', backref='commune', lazy=True, cascade='all, delete-orphan')
    
    # Index composite pour éviter les doublons
    __table_args__ = (db.UniqueConstraint('departement_id', 'code', name='uq_commune_departement_code'),)
    
    def to_dict(self):
        return {
            'id': self.id,
            'departement_id': self.departement_id,
            'departement_nom': self.departement.nom if self.departement else None,
            'pays_nom': self.departement.pays.nom if self.departement and self.departement.pays else None,
            'code': self.code,
            'nom': self.nom,
            'active': self.active
        }


class QuartierVillage(db.Model):
    """Modèle pour les quartiers et villages"""
    __tablename__ = 'quartiers_villages'
    
    id = db.Column(db.Integer, primary_key=True)
    commune_id = db.Column(db.Integer, db.ForeignKey('communes.id'), nullable=False)
    code = db.Column(db.String(20), nullable=False, index=True)
    nom = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(20), default='quartier')  # 'quartier' ou 'village'
    active = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Index composite pour éviter les doublons
    __table_args__ = (db.UniqueConstraint('commune_id', 'code', name='uq_quartier_commune_code'),)
    
    def to_dict(self):
        return {
            'id': self.id,
            'commune_id': self.commune_id,
            'commune_nom': self.commune.nom if self.commune else None,
            'departement_nom': self.commune.departement.nom if self.commune and self.commune.departement else None,
            'pays_nom': self.commune.departement.pays.nom if self.commune and self.commune.departement and self.commune.departement.pays else None,
            'code': self.code,
            'nom': self.nom,
            'type': self.type,
            'active': self.active
        }


class Marche(db.Model):
    """Modèle pour les marchés"""
    __tablename__ = 'marches'
    
    id = db.Column(db.Integer, primary_key=True)
    quartier_village_id = db.Column(db.Integer, db.ForeignKey('quartiers_villages.id'), nullable=True)
    code = db.Column(db.String(20), nullable=False, index=True)
    nom = db.Column(db.String(100), nullable=False)
    adresse = db.Column(db.String(500))
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    quartier_village = db.relationship('QuartierVillage', backref='marches', lazy=True)
    boutiques = db.relationship('Boutique', backref='marche_entity', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'quartier_village_id': self.quartier_village_id,
            'quartier_nom': self.quartier_village.nom if self.quartier_village else None,
            'commune_nom': self.quartier_village.commune.nom if self.quartier_village and self.quartier_village.commune else None,
            'code': self.code,
            'nom': self.nom,
            'adresse': self.adresse,
            'description': self.description,
            'active': self.active,
            'date_creation': self.date_creation.isoformat() if self.date_creation else None
        }


DEFAULT_SECTEURS_ACTIVITE = [
    {'code': 'COMMERCE', 'nom': 'Commerce', 'ordre': 1, 'color': '#0d9668', 'icon': '🏪'},
    {'code': 'RESTAURATION', 'nom': 'Restauration & Hébergement', 'ordre': 2, 'color': '#e67e22', 'icon': '🍽️'},
    {'code': 'SERVICES', 'nom': 'Services', 'ordre': 3, 'color': '#3498db', 'icon': '🔧'},
    {'code': 'EDUCATION', 'nom': 'Éducation', 'ordre': 4, 'color': '#9b59b6', 'icon': '🎓'},
    {'code': 'AUTRE', 'nom': 'Autre', 'ordre': 99, 'color': '#7f8c8d', 'icon': '📍'},
]

POI_STATUTS_VALIDATION = ('brouillon', 'en_attente', 'valide', 'rejete')


class SecteurActivite(db.Model):
    """Secteur d'activité (regroupement des types POI — modèle GéoRéf)"""
    __tablename__ = 'secteurs_activite'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    nom = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    icon = db.Column(db.String(20))
    color = db.Column(db.String(7), default='#0d9668')
    ordre = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    types_commerce = db.relationship('TypeCommerce', back_populates='secteur', lazy=True)

    def to_dict(self, include_types=False):
        result = {
            'id': self.id,
            'code': self.code,
            'nom': self.nom,
            'description': self.description,
            'icon': self.icon,
            'color': self.color,
            'ordre': self.ordre,
            'active': self.active,
            'types_count': len([t for t in self.types_commerce if t.active]),
            'date_creation': self.date_creation.isoformat() if self.date_creation else None,
        }
        if include_types:
            result['types_commerce'] = [
                t.to_dict(include_champs=False) for t in sorted(self.types_commerce, key=lambda x: (x.ordre, x.nom))
                if t.active
            ]
        return result


class TypeCommerce(db.Model):
    """Type d'activité POI (équivalent sous-secteur GéoRéf)"""
    __tablename__ = 'types_commerce'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    nom = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    nature_poi_id = db.Column(db.Integer, db.ForeignKey('natures_poi.id'), nullable=True)
    secteur_id = db.Column(db.Integer, db.ForeignKey('secteurs_activite.id'), nullable=True)
    icon = db.Column(db.String(20))
    color = db.Column(db.String(7))
    map_line_style = db.Column(db.String(30), default='solid')
    map_fill_pattern = db.Column(db.String(30), default='solid')
    ordre = db.Column(db.Integer, default=0)

    # Relations
    nature_poi_ref = db.relationship('NaturePoi', foreign_keys=[nature_poi_id], lazy=True)
    secteur = db.relationship('SecteurActivite', back_populates='types_commerce', lazy=True)
    boutiques = db.relationship('Boutique', backref='type_commerce', lazy=True)
    champs = db.relationship(
        'ChampPoi',
        back_populates='type_commerce',
        lazy=True,
        cascade='all, delete-orphan',
        foreign_keys='ChampPoi.type_commerce_id',
        order_by='ChampPoi.ordre',
    )

    def get_champs_actifs(self):
        return [c for c in self.champs if c.active]

    def to_dict(self, include_champs=False):
        return {
            'id': self.id,
            'code': self.code,
            'nom': self.nom,
            'description': self.description,
            'active': self.active,
            'nature_poi_id': self.nature_poi_id,
            'nature_poi': self.nature_poi_ref.to_dict(include_champs=False) if self.nature_poi_ref else None,
            'secteur_id': self.secteur_id,
            'secteur': self.secteur.to_dict() if self.secteur else None,
            'icon': self.icon,
            'color': self.color,
            'map_line_style': self.map_line_style or 'solid',
            'map_fill_pattern': self.map_fill_pattern or 'solid',
            'ordre': self.ordre,
            'champs_count': len(self.get_champs_actifs()),
            'champs': [c.to_dict() for c in self.get_champs_actifs()] if include_champs else None,
            'date_creation': self.date_creation.isoformat() if self.date_creation else None,
        }


class Boutique(db.Model):
    """Modèle pour les boutiques"""
    __tablename__ = 'boutiques'
    
    id = db.Column(db.Integer, primary_key=True)
    code_unique = db.Column(db.String(50), unique=True, nullable=False, index=True)
    nom = db.Column(db.String(200), nullable=False)
    proprietaire = db.Column(db.String(200))
    telephone = db.Column(db.String(20))
    adresse = db.Column(db.String(500))
    
    # Type de commerce
    type_commerce_id = db.Column(db.Integer, db.ForeignKey('types_commerce.id'), nullable=True)
    
    # Anciens champs (conservés pour compatibilité)
    arrondissement = db.Column(db.String(100))
    zone = db.Column(db.String(100))
    marche = db.Column(db.String(100))
    
    # Rattachement pays (multi-pays, optionnel si hiérarchie admin complète)
    pays_id = db.Column(db.Integer, db.ForeignKey('pays.id'), nullable=True, index=True)
    quartier_village_id = db.Column(db.Integer, db.ForeignKey('quartiers_villages.id'))
    marche_id = db.Column(db.Integer, db.ForeignKey('marches.id'), nullable=True)  # Nouvelle relation
    marche_nom = db.Column(db.String(100))  # Nom du marché (conservé pour compatibilité)
    
    # Géolocalisation
    latitude = db.Column(db.Float)  # Latitude GPS
    longitude = db.Column(db.Float)  # Longitude GPS

    # POI unifié : catégorie métier + forme géométrique
    categorie = db.Column(db.String(20), default='contribuable', index=True)  # contribuable | infrastructure
    feature_type = db.Column(db.String(20), default='point', index=True)  # point | pylon | pipeline | parcel | perimeter
    geometry = db.Column(db.Text)  # GeoJSON
    description = db.Column(db.Text)
    properties = db.Column(db.Text)  # JSON (radius_m, donnees techniques legacy…)
    length_m = db.Column(db.Float)
    area_ha = db.Column(db.Float)
    perimeter_m = db.Column(db.Float)
    radius_m = db.Column(db.Float)
    legacy_map_feature_id = db.Column(db.Integer, nullable=True)

    # Géo-tax : nature du POI et données administratives (JSON) pour statistiques
    nature_poi = db.Column(db.String(40), default='autre', index=True)
    donnees_administratives = db.Column(db.Text)  # JSON sérialisé

    # Validation collecte (modèle GéoRéf)
    statut_validation = db.Column(db.String(20), default='valide', index=True)
    photo_path = db.Column(db.String(500))
    collector_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    validated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    validated_at = db.Column(db.DateTime)
    validation_comment = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime)
    
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    qr_code_path = db.Column(db.String(500))
    active = db.Column(db.Boolean, default=True)
    
    # Relations
    pays = db.relationship('Pays', foreign_keys=[pays_id], lazy=True)
    quartier_village = db.relationship('QuartierVillage', backref='boutiques', lazy=True)
    paiements = db.relationship('Paiement', backref='boutique', lazy=True, cascade='all, delete-orphan')
    taxes = db.relationship('BoutiqueTaxe', backref='boutique', lazy=True, cascade='all, delete-orphan')
    
    def get_donnees_admin_parsed(self):
        if not self.donnees_administratives:
            return {}
        try:
            return json.loads(self.donnees_administratives)
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_geometry_parsed(self):
        if self.geometry:
            try:
                return json.loads(self.geometry)
            except (json.JSONDecodeError, TypeError):
                pass
        if self.feature_type == 'point' and self.latitude is not None and self.longitude is not None:
            return {'type': 'Point', 'coordinates': [float(self.longitude), float(self.latitude)]}
        return {}

    def get_properties_parsed(self):
        if not self.properties:
            return {}
        try:
            return json.loads(self.properties)
        except (json.JSONDecodeError, TypeError):
            return {}

    def is_contribuable(self):
        return (self.categorie or 'contribuable') == 'contribuable'

    def is_infrastructure(self):
        return (self.categorie or '') == 'infrastructure'

    def get_feature_type_meta(self):
        from geo_metrics import MAP_FEATURE_TYPES
        ft = self.feature_type or 'point'
        if ft == 'point':
            return {'label': 'Point', 'icon': '📍', 'color': '#0d9668'}
        return MAP_FEATURE_TYPES.get(ft, {
            'label': ft,
            'icon': '📍',
            'color': '#607d8b',
        })

    def sync_coords_from_geometry(self):
        """Met à jour latitude/longitude depuis le centroïde de la géométrie."""
        from geo_metrics import geometry_centroid
        geom = self.get_geometry_parsed()
        if not geom:
            return
        centroid = geometry_centroid(geom)
        if centroid:
            self.latitude, self.longitude = centroid

    def get_map_style(self):
        """Style carte (couleur, trait, remplissage) depuis le type d'activité."""
        tc = self.type_commerce
        if tc:
            return {
                'color': self.get_display_color(),
                'line_style': tc.map_line_style or 'solid',
                'fill_pattern': tc.map_fill_pattern or 'solid',
            }
        return {
            'color': self.get_display_color(),
            'line_style': 'solid',
            'fill_pattern': 'solid',
        }

    def get_display_color(self):
        """Couleur carte : type d'activité, puis secteur, sinon gris neutre."""
        tc = self.type_commerce
        if tc:
            if tc.color:
                return tc.color
            if tc.secteur and tc.secteur.color:
                return tc.secteur.color
        return '#607d8b'

    def to_geojson_feature(self):
        """Feature GeoJSON pour affichage carte (formes non-point ou avec geometry)."""
        props = self.to_dict()
        geometry = props.pop('geometry', self.get_geometry_parsed())
        props['name'] = self.nom
        props['source'] = 'poi'
        return {
            'type': 'Feature',
            'id': self.id,
            'geometry': geometry,
            'properties': props,
        }

    def to_dict(self):
        try:
            nat = NaturePoi.normalize_code(self.nature_poi)
            result = {
                'id': self.id,
                'code_unique': self.code_unique,
                'nom': self.nom,
                'proprietaire': self.proprietaire,
                'telephone': self.telephone,
                'adresse': self.adresse,
                'date_creation': self.date_creation.isoformat() if self.date_creation else None,
                'active': self.active,
                'marche_id': self.marche_id,
                'marche_nom': self.marche_nom,
                'marche_nom_entity': self.marche_entity.nom if hasattr(self, 'marche_entity') and self.marche_entity else None,
                'latitude': float(self.latitude) if self.latitude is not None else None,
                'longitude': float(self.longitude) if self.longitude is not None else None,
                'pays_id': self.pays_id,
                'categorie': self.categorie or 'contribuable',
                'feature_type': self.feature_type or 'point',
                'feature_type_label': self.get_feature_type_meta().get('label', 'Point'),
                'feature_type_icon': self.get_feature_type_meta().get('icon', '📍'),
                'feature_type_color': self.get_feature_type_meta().get('color', '#0d9668'),
                'display_color': self.get_display_color(),
                'map_style': self.get_map_style(),
                'geometry': self.get_geometry_parsed(),
                'description': self.description,
                'properties': self.get_properties_parsed(),
                'length_m': self.length_m,
                'area_ha': self.area_ha,
                'perimeter_m': self.perimeter_m,
                'radius_m': self.radius_m,
                'type_commerce_id': self.type_commerce_id,
                'type_commerce': self.type_commerce.to_dict() if self.type_commerce else None,
                'nature_poi': nat,
                'nature_poi_label': NaturePoi.get_label_for_code(nat),
                'donnees_administratives': self.get_donnees_admin_parsed(),
                'statut_validation': self.statut_validation or 'valide',
                'photo_path': self.photo_path,
                'photo_url': f'/uploads/poi/{os.path.basename(self.photo_path)}' if self.photo_path else None,
                'collector_id': self.collector_id,
                'validated_by': self.validated_by,
                'validated_at': self.validated_at.isoformat() if self.validated_at else None,
                'validation_comment': self.validation_comment,
                'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
                'taxes': [bt.to_dict() for bt in self.taxes if bt.active] if self.taxes else []
            }
            
            # Anciens champs (pour compatibilité)
            result['arrondissement'] = self.arrondissement
            result['zone'] = self.zone
            result['marche'] = self.marche
            
            # Nouvelles relations géographiques
            try:
                if self.quartier_village:
                    result['quartier_village'] = self.quartier_village.to_dict()
                    try:
                        if self.quartier_village.commune:
                            result['commune'] = self.quartier_village.commune.to_dict()
                            try:
                                if self.quartier_village.commune.departement:
                                    result['departement'] = self.quartier_village.commune.departement.to_dict()
                                    try:
                                        if self.quartier_village.commune.departement.pays:
                                            result['pays'] = self.quartier_village.commune.departement.pays.to_dict()
                                    except:
                                        result['pays'] = None
                            except:
                                result['departement'] = None
                                result['pays'] = None
                    except:
                        result['commune'] = None
                        result['departement'] = None
                        result['pays'] = None
                else:
                    result['quartier_village'] = None
                    result['commune'] = None
                    result['departement'] = None
                    if self.pays_id and self.pays:
                        result['pays'] = self.pays.to_dict()
                    else:
                        result['pays'] = None
            except Exception as e:
                # En cas d'erreur avec les relations, on met None
                result['quartier_village'] = None
                result['commune'] = None
                result['departement'] = None
                result['pays'] = None
            
            return result
        except Exception as e:
            # En cas d'erreur majeure, retourner au moins les champs de base
            print(f"Erreur dans to_dict() pour boutique {self.id}: {e}")
            import traceback
            traceback.print_exc()
            nat = NaturePoi.normalize_code(self.nature_poi)
            return {
                'id': self.id,
                'code_unique': self.code_unique,
                'nom': self.nom,
                'proprietaire': self.proprietaire or '',
                'telephone': self.telephone or '',
                'adresse': self.adresse or '',
                'arrondissement': self.arrondissement or '',
                'zone': self.zone or '',
                'marche': self.marche or '',
                'date_creation': None,
                'active': self.active,
                'marche_nom': self.marche_nom or '',
                'latitude': self.latitude,
                'longitude': self.longitude,
                'type_commerce_id': self.type_commerce_id,
                'type_commerce': self.type_commerce.to_dict() if self.type_commerce else None,
                'marche_id': self.marche_id,
                'nature_poi': nat,
                'nature_poi_label': NaturePoi.get_label_for_code(nat),
                'donnees_administratives': self.get_donnees_admin_parsed(),
                'taxes': []
            }
    
    def get_statut_paiement_mois(self, mois=None, annee=None):
        """Vérifie si la boutique est à jour pour le mois : toutes les taxes exigibles doivent être recouvrées."""
        if mois is None:
            mois = datetime.utcnow().month
        if annee is None:
            annee = datetime.utcnow().year

        boutique_taxes = BoutiqueTaxe.query.filter_by(boutique_id=self.id, active=True).all()
        if not boutique_taxes:
            return True

        debut_boutique = self.date_creation or datetime.utcnow()

        for bt in boutique_taxes:
            taxe = bt.taxe
            if not taxe or not taxe.active:
                continue

            debut = bt.date_application or debut_boutique
            if debut_boutique > debut:
                debut = debut_boutique
            debut_m, debut_a = debut.month, debut.year

            if not self._taxe_est_due(taxe, mois, annee, debut_m, debut_a):
                continue

            montant_attendu = bt.montant_personnalise if bt.montant_personnalise else taxe.montant_attendu
            paiement = Paiement.query.filter_by(
                boutique_id=self.id,
                taxe_id=taxe.id,
                mois=mois,
                annee=annee,
                statut='confirme'
            ).first()
            if paiement is None or paiement.montant < montant_attendu:
                return False

        return True
    
    def get_dernier_paiement(self):
        """Retourne le dernier paiement confirmé"""
        return Paiement.query.filter_by(
            boutique_id=self.id,
            statut='confirme'
        ).order_by(Paiement.date_paiement.desc()).first()

    @staticmethod
    def _iter_mois_periodes(debut_mois, debut_annee, fin_mois, fin_annee):
        """Itère les couples (mois, année) de la période de début à la période de fin incluses."""
        m, a = debut_mois, debut_annee
        while (a, m) <= (fin_annee, fin_mois):
            yield m, a
            m += 1
            if m > 12:
                m = 1
                a += 1

    @staticmethod
    def _taxe_est_due(taxe, mois, annee, debut_mois, debut_annee):
        """Indique si une taxe est exigible pour le mois/année donné."""
        if (annee, mois) < (debut_annee, debut_mois):
            return False
        periodicite = (taxe.periodicite or 'mensuel').lower()
        if periodicite == 'mensuel':
            return True
        if periodicite == 'trimestriel':
            months_since_start = (annee - debut_annee) * 12 + (mois - debut_mois)
            return months_since_start >= 0 and months_since_start % 3 == 0
        if periodicite == 'annuel':
            return mois == debut_mois
        if periodicite == 'ponctuel':
            return mois == debut_mois and annee == debut_annee
        return True

    def get_statut_paiement_periode(self, mois_debut, annee_debut, mois_fin, annee_fin):
        """Vérifie si le POI est à jour pour chaque mois de l'intervalle."""
        for m, a in self._iter_mois_periodes(mois_debut, annee_debut, mois_fin, annee_fin):
            if not self.get_statut_paiement_mois(m, a):
                return False
        return True

    def get_statut_paiement_global(self, mois_fin=None, annee_fin=None):
        """À jour seulement si aucune taxe exigible n'est impayée depuis la création du POI."""
        if mois_fin is None:
            mois_fin = datetime.utcnow().month
        if annee_fin is None:
            annee_fin = datetime.utcnow().year
        debut = self.date_creation or datetime.utcnow()
        return self.get_statut_paiement_periode(debut.month, debut.year, mois_fin, annee_fin)

    def get_montants_periode(self, mois_debut, annee_debut, mois_fin, annee_fin):
        """Montants attendus, recouvrés et restant à recouvrer sur un intervalle de mois."""
        montant_attendu = 0.0
        montant_recouvre = 0.0

        paiements = Paiement.query.filter_by(boutique_id=self.id, statut='confirme').all()
        paiements_map = {
            (p.taxe_id, p.mois, p.annee): p.montant
            for p in paiements if p.taxe_id
        }

        debut_boutique = self.date_creation or datetime.utcnow()
        boutique_taxes = BoutiqueTaxe.query.filter_by(boutique_id=self.id, active=True).all()

        for bt in boutique_taxes:
            taxe = bt.taxe
            if not taxe or not taxe.active:
                continue
            montant = bt.montant_personnalise if bt.montant_personnalise else taxe.montant_attendu

            debut = bt.date_application or debut_boutique
            if debut_boutique > debut:
                debut = debut_boutique
            debut_m, debut_a = debut.month, debut.year

            for m, a in self._iter_mois_periodes(mois_debut, annee_debut, mois_fin, annee_fin):
                if not self._taxe_est_due(taxe, m, a, debut_m, debut_a):
                    continue
                montant_attendu += montant
                montant_recouvre += paiements_map.get((taxe.id, m, a), 0.0)

        montant_a_recouvrer = max(0.0, montant_attendu - montant_recouvre)
        return {
            'montant_attendu': round(montant_attendu, 2),
            'montant_recouvre': round(montant_recouvre, 2),
            'montant_a_recouvrer': round(montant_a_recouvrer, 2),
        }

    def get_montants_mois(self, mois=None, annee=None):
        """Montants cumulés depuis la création du POI jusqu'à la période indiquée."""
        if mois is None:
            mois = datetime.utcnow().month
        if annee is None:
            annee = datetime.utcnow().year
        debut = self.date_creation or datetime.utcnow()
        return self.get_montants_periode(debut.month, debut.year, mois, annee)

    def get_releve_paiements(self, mois_fin=None, annee_fin=None, mois_debut=None, annee_debut=None):
        """Relevé détaillé : chaque période/taxe avec montants et état de recouvrement."""
        if mois_fin is None:
            mois_fin = datetime.utcnow().month
        if annee_fin is None:
            annee_fin = datetime.utcnow().year
        if mois_debut is None or annee_debut is None:
            debut = self.date_creation or datetime.utcnow()
            mois_debut = debut.month
            annee_debut = debut.year

        mois_noms = [
            'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
            'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre'
        ]

        all_paiements = Paiement.query.filter_by(boutique_id=self.id).all()
        paiements_by_key = {}
        for p in all_paiements:
            if p.taxe_id:
                key = (p.taxe_id, p.mois, p.annee)
                paiements_by_key.setdefault(key, []).append(p)

        debut_boutique = self.date_creation or datetime.utcnow()
        boutique_taxes = BoutiqueTaxe.query.filter_by(boutique_id=self.id, active=True).all()
        lignes = []

        for bt in boutique_taxes:
            taxe = bt.taxe
            if not taxe or not taxe.active:
                continue
            montant = bt.montant_personnalise if bt.montant_personnalise else taxe.montant_attendu
            institut_nom = taxe.institut.nom if taxe.institut else 'Inconnu'

            debut = bt.date_application or debut_boutique
            if debut_boutique > debut:
                debut = debut_boutique
            debut_m, debut_a = debut.month, debut.year

            for m, a in self._iter_mois_periodes(mois_debut, annee_debut, mois_fin, annee_fin):
                if not self._taxe_est_due(taxe, m, a, debut_m, debut_a):
                    continue

                paiements = paiements_by_key.get((taxe.id, m, a), [])
                paiement_confirme = next((p for p in paiements if p.statut == 'confirme'), None)
                paiement_attente = next((p for p in paiements if p.statut == 'en_attente'), None)

                montant_paye = paiement_confirme.montant if paiement_confirme else 0.0
                montant_restant = max(0.0, montant - montant_paye)

                if paiement_confirme and montant_paye >= montant:
                    etat = 'recouvre'
                elif paiement_confirme and montant_paye > 0:
                    etat = 'partiel'
                elif paiement_attente:
                    etat = 'en_attente'
                else:
                    etat = 'non_recouvre'

                paiement_ref = paiement_confirme or paiement_attente
                lignes.append({
                    'taxe_id': taxe.id,
                    'taxe_nom': taxe.nom,
                    'taxe_code': taxe.code,
                    'institut_nom': institut_nom,
                    'mois': m,
                    'annee': a,
                    'periode_label': f"{mois_noms[m - 1]} {a}",
                    'montant_attendu': round(montant, 2),
                    'montant_recouvre': round(montant_paye, 2),
                    'montant_restant': round(montant_restant, 2),
                    'etat': etat,
                    'paiement': paiement_ref.to_dict() if paiement_ref else None,
                })

        lignes.sort(key=lambda x: (-x['annee'], -x['mois'], x['taxe_nom']))
        totaux = self.get_montants_periode(mois_debut, annee_debut, mois_fin, annee_fin)

        return {
            'lignes': lignes,
            'totaux': totaux,
            'mois_debut': mois_debut,
            'annee_debut': annee_debut,
            'mois_fin': mois_fin,
            'annee_fin': annee_fin,
            'nombre_recouvre': sum(1 for l in lignes if l['etat'] == 'recouvre'),
            'nombre_non_recouvre': sum(1 for l in lignes if l['etat'] == 'non_recouvre'),
            'nombre_partiel': sum(1 for l in lignes if l['etat'] == 'partiel'),
            'nombre_en_attente': sum(1 for l in lignes if l['etat'] == 'en_attente'),
        }


class BoutiqueTaxe(db.Model):
    """Table de liaison entre Boutique et Taxe avec montant personnalisé"""
    __tablename__ = 'boutique_taxes'
    
    id = db.Column(db.Integer, primary_key=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False, index=True)
    taxe_id = db.Column(db.Integer, db.ForeignKey('taxes.id'), nullable=False, index=True)
    montant_personnalise = db.Column(db.Float, nullable=True)  # Montant personnalisé pour ce commerce (si différent du montant attendu)
    date_application = db.Column(db.DateTime, default=datetime.utcnow)
    active = db.Column(db.Boolean, default=True)
    
    # Relations
    taxe = db.relationship('Taxe', backref='boutique_taxes', lazy=True)
    
    # Index composite pour éviter les doublons
    __table_args__ = (db.UniqueConstraint('boutique_id', 'taxe_id', name='uq_boutique_taxe'),)
    
    def to_dict(self):
        try:
            taxe_dict = None
            montant_a_payer = 0
            if hasattr(self, 'taxe') and self.taxe:
                taxe_dict = self.taxe.to_dict()
                montant_a_payer = self.montant_personnalise if self.montant_personnalise else self.taxe.montant_attendu
            elif self.taxe_id:
                # Si la relation n'est pas chargée, on peut essayer de la charger
                from models import Taxe
                taxe = Taxe.query.get(self.taxe_id)
                if taxe:
                    taxe_dict = taxe.to_dict()
                    montant_a_payer = self.montant_personnalise if self.montant_personnalise else taxe.montant_attendu
            
            return {
                'id': self.id,
                'boutique_id': self.boutique_id,
                'taxe_id': self.taxe_id,
                'taxe': taxe_dict,
                'montant_personnalise': self.montant_personnalise,
                'montant_a_payer': montant_a_payer,
                'date_application': self.date_application.isoformat() if self.date_application else None,
                'active': self.active
            }
        except Exception as e:
            print(f"Erreur dans BoutiqueTaxe.to_dict() pour ID {self.id}: {e}")
            return {
                'id': self.id,
                'boutique_id': self.boutique_id,
                'taxe_id': self.taxe_id,
                'taxe': None,
                'montant_personnalise': self.montant_personnalise,
                'montant_a_payer': self.montant_personnalise or 0,
                'date_application': self.date_application.isoformat() if self.date_application else None,
                'active': self.active
            }


class Taxe(db.Model):
    """Modèle pour les taxes par institution"""
    __tablename__ = 'taxes'
    
    id = db.Column(db.Integer, primary_key=True)
    institut_id = db.Column(db.Integer, db.ForeignKey('instituts.id'), nullable=False, index=True)
    code = db.Column(db.String(50), nullable=False, index=True)
    nom = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    montant_attendu = db.Column(db.Float, nullable=False)  # Montant attendu en FCFA
    periodicite = db.Column(db.String(20), default='mensuel')  # 'mensuel', 'trimestriel', 'annuel', 'ponctuel'
    active = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    paiements = db.relationship('Paiement', backref='taxe', lazy=True)
    
    # Index composite pour éviter les doublons
    __table_args__ = (db.UniqueConstraint('institut_id', 'code', name='uq_taxe_institut_code'),)
    
    def to_dict(self):
        return {
            'id': self.id,
            'institut_id': self.institut_id,
            'institut_nom': self.institut.nom if self.institut else None,
            'institut_code': self.institut.code if self.institut else None,
            'code': self.code,
            'nom': self.nom,
            'description': self.description,
            'montant_attendu': self.montant_attendu,
            'periodicite': self.periodicite,
            'active': self.active,
            'date_creation': self.date_creation.isoformat() if self.date_creation else None
        }


class Paiement(db.Model):
    """Modèle pour les paiements"""
    __tablename__ = 'paiements'
    
    id = db.Column(db.Integer, primary_key=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False)
    institut_id = db.Column(db.Integer, db.ForeignKey('instituts.id'), nullable=False, index=True)
    taxe_id = db.Column(db.Integer, db.ForeignKey('taxes.id'), nullable=True, index=True)
    montant = db.Column(db.Float, nullable=False)
    mois = db.Column(db.Integer, nullable=False)  # 1-12
    annee = db.Column(db.Integer, nullable=False)
    date_paiement = db.Column(db.DateTime, default=datetime.utcnow)
    methode = db.Column(db.String(50))  # 'USSD', 'MTN_MONEY', 'AIRTEL_MONEY', 'AUTRE'
    numero_transaction = db.Column(db.String(30), unique=True, index=True)  # TXN-YYYY-NNNNNN
    reference_transaction = db.Column(db.String(100), unique=True)
    numero_telephone = db.Column(db.String(20))
    statut = db.Column(db.String(20), default='en_attente')  # 'en_attente', 'confirme', 'annule'
    notes = db.Column(db.Text)
    
    def to_dict(self):
        return {
            'id': self.id,
            'boutique_id': self.boutique_id,
            'boutique_code': self.boutique.code_unique if self.boutique else None,
            'boutique_nom': self.boutique.nom if self.boutique else None,
            'institut_id': self.institut_id,
            'institut_nom': self.institut.nom if self.institut else None,
            'institut_code': self.institut.code if self.institut else None,
            'taxe_id': self.taxe_id,
            'taxe_nom': self.taxe.nom if self.taxe else None,
            'taxe_code': self.taxe.code if self.taxe else None,
            'montant_attendu': self.taxe.montant_attendu if self.taxe else None,
            'montant': self.montant,
            'mois': self.mois,
            'annee': self.annee,
            'date_paiement': self.date_paiement.isoformat() if self.date_paiement else None,
            'methode': self.methode,
            'numero_transaction': self.numero_transaction,
            'reference_transaction': self.reference_transaction,
            'numero_telephone': self.numero_telephone,
            'statut': self.statut,
            'notes': self.notes
        }


class User(db.Model):
    """Utilisateur du système (agents, conseillers, admin)"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    nom = db.Column(db.String(200))
    role = db.Column(db.String(50), nullable=False)  # agent_terrain, agent_financier, conseiller_municipal, admin
    actif = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'nom': self.nom,
            'role': self.role,
            'actif': self.actif,
            'date_creation': self.date_creation.isoformat() if self.date_creation else None
        }


class Commercant(db.Model):
    """Compte commerçant pour suivre l'historique des paiements"""
    __tablename__ = 'commercants'
    
    id = db.Column(db.Integer, primary_key=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False, unique=True)
    telephone = db.Column(db.String(20), nullable=False)
    mot_de_passe_hash = db.Column(db.String(256), nullable=False)
    must_change_password = db.Column(db.Boolean, default=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    actif = db.Column(db.Boolean, default=True)
    
    # Relations
    boutique = db.relationship('Boutique', backref=db.backref('commercant', uselist=False), lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'boutique_id': self.boutique_id,
            'boutique_code': self.boutique.code_unique if self.boutique else None,
            'boutique_nom': self.boutique.nom if self.boutique else None,
            'telephone': self.telephone,
            'must_change_password': bool(self.must_change_password),
            'date_creation': self.date_creation.isoformat() if self.date_creation else None,
            'actif': self.actif
        }


class CollecteTerrain(db.Model):
    """Journal des collectes terrain : date/heure, secteur, collecteur, commerce"""
    __tablename__ = 'collectes_terrain'
    
    id = db.Column(db.Integer, primary_key=True)
    date_heure = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    secteur = db.Column(db.String(200))  # Quartier, commune, zone...
    collecteur_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False, index=True)
    
    # Relations
    collecteur = db.relationship('User', backref='collectes_terrain', lazy=True)
    boutique = db.relationship('Boutique', backref='collectes_terrain', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'date_heure': self.date_heure.isoformat() if self.date_heure else None,
            'secteur': self.secteur or '',
            'collecteur_id': self.collecteur_id,
            'collecteur_nom': self.collecteur.nom if self.collecteur else None,
            'collecteur_username': self.collecteur.username if self.collecteur else None,
            'boutique_id': self.boutique_id,
            'boutique_code': self.boutique.code_unique if self.boutique else None,
            'boutique_nom': self.boutique.nom if self.boutique else None
        }


class MapFeature(db.Model):
    """Entité géographique avancée : pylône, pipeline, parcelle, périmètre."""
    __tablename__ = 'map_features'

    id = db.Column(db.Integer, primary_key=True)
    code_unique = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    feature_type = db.Column(db.String(20), nullable=False, index=True)
    geometry = db.Column(db.Text, nullable=False)
    properties = db.Column(db.Text)
    length_m = db.Column(db.Float)
    area_ha = db.Column(db.Float)
    perimeter_m = db.Column(db.Float)
    radius_m = db.Column(db.Float)
    description = db.Column(db.Text)
    type_commerce_id = db.Column(db.Integer, db.ForeignKey('types_commerce.id'), nullable=True)
    statut_validation = db.Column(db.String(20), default='brouillon', index=True)
    active = db.Column(db.Boolean, default=True)
    collector_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    validated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    validated_at = db.Column(db.DateTime)
    validation_comment = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_modification = db.Column(db.DateTime, onupdate=datetime.utcnow)

    type_commerce = db.relationship('TypeCommerce', backref='map_features', lazy=True)

    @staticmethod
    def generate_code():
        return f'GEO-{datetime.utcnow().strftime("%Y%m%d%H%M%S")}'

    def get_geometry_parsed(self):
        if not self.geometry:
            return {}
        try:
            return json.loads(self.geometry)
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_properties_parsed(self):
        if not self.properties:
            return {}
        try:
            return json.loads(self.properties)
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_type_meta(self):
        from geo_metrics import MAP_FEATURE_TYPES
        return MAP_FEATURE_TYPES.get(self.feature_type, {
            'label': self.feature_type,
            'icon': '📍',
            'color': '#607d8b',
        })

    def to_dict(self):
        props = self.get_properties_parsed()
        meta = self.get_type_meta()
        return {
            'id': self.id,
            'code_unique': self.code_unique,
            'name': self.name,
            'feature_type': self.feature_type,
            'feature_type_label': meta.get('label', self.feature_type),
            'feature_type_icon': meta.get('icon', '📍'),
            'feature_type_color': meta.get('color', '#607d8b'),
            'geometry': self.get_geometry_parsed(),
            'properties': props,
            'length_m': self.length_m,
            'area_ha': self.area_ha,
            'perimeter_m': self.perimeter_m,
            'radius_m': self.radius_m,
            'description': self.description,
            'type_commerce_id': self.type_commerce_id,
            'type_commerce': self.type_commerce.to_dict() if self.type_commerce else None,
            'statut_validation': self.statut_validation or 'brouillon',
            'active': self.active,
            'collector_id': self.collector_id,
            'validated_by': self.validated_by,
            'validated_at': self.validated_at.isoformat() if self.validated_at else None,
            'validation_comment': self.validation_comment,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'date_creation': self.date_creation.isoformat() if self.date_creation else None,
            'source': 'map_feature',
            'collecte_kind': self.feature_type,
        }

    def to_geojson_feature(self):
        props = self.to_dict()
        geometry = props.pop('geometry', {})
        return {
            'type': 'Feature',
            'id': self.id,
            'geometry': geometry,
            'properties': props,
        }


class Configuration(db.Model):
    """Modèle pour les configurations système"""
    __tablename__ = 'configurations'
    
    id = db.Column(db.Integer, primary_key=True)
    cle = db.Column(db.String(100), unique=True, nullable=False)
    valeur = db.Column(db.Text)
    description = db.Column(db.String(500))
    
    @staticmethod
    def get(cle, default=None):
        config = Configuration.query.filter_by(cle=cle).first()
        return config.valeur if config else default
    
    @staticmethod
    def set(cle, valeur, description=None):
        config = Configuration.query.filter_by(cle=cle).first()
        if config:
            config.valeur = valeur
            if description:
                config.description = description
        else:
            config = Configuration(cle=cle, valeur=valeur, description=description)
            db.session.add(config)
        db.session.commit()
        return config



class ContactRequest(db.Model):
    """Demande de contact / démonstration reçue depuis la landing page."""
    __tablename__ = 'contact_requests'

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(120), nullable=False)
    organisation = db.Column(db.String(160))
    telephone = db.Column(db.String(60))
    email = db.Column(db.String(160))
    activite = db.Column(db.String(160))
    type_besoin = db.Column(db.String(120))
    message = db.Column(db.Text)
    ip = db.Column(db.String(60))
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    traite = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {
            'id': self.id,
            'nom': self.nom,
            'organisation': self.organisation,
            'telephone': self.telephone,
            'email': self.email,
            'activite': self.activite,
            'type_besoin': self.type_besoin,
            'message': self.message,
            'date_creation': self.date_creation.isoformat() if self.date_creation else None,
            'traite': self.traite,
        }

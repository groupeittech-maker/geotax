from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


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
            'active': self.active
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


class TypeCommerce(db.Model):
    """Modèle pour les types de commerce"""
    __tablename__ = 'types_commerce'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    nom = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    boutiques = db.relationship('Boutique', backref='type_commerce', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'nom': self.nom,
            'description': self.description,
            'active': self.active,
            'date_creation': self.date_creation.isoformat() if self.date_creation else None
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
    
    # Nouvelles relations géographiques
    quartier_village_id = db.Column(db.Integer, db.ForeignKey('quartiers_villages.id'))
    marche_id = db.Column(db.Integer, db.ForeignKey('marches.id'), nullable=True)  # Nouvelle relation
    marche_nom = db.Column(db.String(100))  # Nom du marché (conservé pour compatibilité)
    
    # Géolocalisation
    latitude = db.Column(db.Float)  # Latitude GPS
    longitude = db.Column(db.Float)  # Longitude GPS
    
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    qr_code_path = db.Column(db.String(500))
    active = db.Column(db.Boolean, default=True)
    
    # Relations
    quartier_village = db.relationship('QuartierVillage', backref='boutiques', lazy=True)
    paiements = db.relationship('Paiement', backref='boutique', lazy=True, cascade='all, delete-orphan')
    taxes = db.relationship('BoutiqueTaxe', backref='boutique', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        try:
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
                'type_commerce_id': self.type_commerce_id,
                'type_commerce': self.type_commerce.to_dict() if self.type_commerce else None,
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
                'taxes': []
            }
    
    def get_statut_paiement_mois(self, mois=None, annee=None):
        """Vérifie si la boutique est à jour pour le mois : TOUTES les taxes doivent être payées.
        S'il reste une seule taxe en retard, le compte n'est pas considéré à jour."""
        if mois is None:
            mois = datetime.utcnow().month
        if annee is None:
            annee = datetime.utcnow().year
        
        # Récupérer toutes les taxes que la boutique doit payer
        boutique_taxes = BoutiqueTaxe.query.filter_by(boutique_id=self.id, active=True).all()
        
        # Si aucune taxe configurée, le compte est considéré à jour
        if not boutique_taxes:
            return True
        
        # Vérifier que CHAQUE taxe a un paiement confirmé pour ce mois
        for bt in boutique_taxes:
            taxe = bt.taxe
            if not taxe or not taxe.active:
                continue
            paiement = Paiement.query.filter_by(
                boutique_id=self.id,
                taxe_id=taxe.id,
                mois=mois,
                annee=annee,
                statut='confirme'
            ).first()
            if paiement is None:
                # Au moins une taxe n'est pas payée → pas à jour
                return False
        
        return True
    
    def get_dernier_paiement(self):
        """Retourne le dernier paiement confirmé"""
        return Paiement.query.filter_by(
            boutique_id=self.id,
            statut='confirme'
        ).order_by(Paiement.date_paiement.desc()).first()


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
            'date_creation': self.date_creation.isoformat() if self.date_creation else None,
            'actif': self.actif
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

